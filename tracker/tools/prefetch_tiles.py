#!/usr/bin/env python3
"""Download satellite imagery and elevation tiles for a route, for the 3D view.

Run it on the ground before the flight; the 3D view then works with no internet:

    python3 tools/prefetch_tiles.py LHR PEK
    python3 tools/prefetch_tiles.py EGLL ZBAA --corridor 2 --jobs 24

Tiles go to static/3d/tex/{sat,dem}/z/x/y, and static/3d/tex/manifest.json lists what
is on disk so the page never asks for tiles it doesn't have.

  * Imagery: Esri World Imagery (attribution required; see ATTRIBUTION.md).
  * Elevation: Terrarium tiles from the AWS Terrain Tiles open dataset.

Roughly 600-900 tiles (40-60 MB) for a 9,000 km flight.
"""
import argparse
import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "static")
TEX = os.path.join(STATIC, "3d", "tex")
UA = "inflight-kit/1.0 (personal in-flight tracker)"
SOURCES = {
    "sat": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "jpg"),
    "dem": ("https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", "png"),
}


def airport(code):
    with open(os.path.join(STATIC, "airports.json"), encoding="utf-8") as f:
        for iata, icao, name, city, lat, lon in json.load(f)["airports"]:
            if code.upper() in (iata, icao):
                return name, lat, lon
    sys.exit(f"Unknown airport {code}; use an IATA or ICAO code from static/airports.json")


def great_circle(a, b, step_km=15):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    n = max(2, int(d * 6371 / step_km))
    for i in range(n + 1):
        f = i / n
        A, B = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = A * math.cos(la1) * math.cos(lo1) + B * math.cos(la2) * math.cos(lo2)
        y = A * math.cos(la1) * math.sin(lo1) + B * math.cos(la2) * math.sin(lo2)
        z = A * math.sin(la1) + B * math.sin(la2)
        yield math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def tile(lat, lon, z):
    n = 2 ** z
    r = math.radians(max(-85, min(85, lat)))
    return int((lon + 180) / 360 * n) % n, int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)


def around(lat, lon, km, z, steps=12):
    """Tiles covering a square of +/- km around a point."""
    out = set()
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            out.add((z,) + tile(lat + i * km / steps / 110.6, lon + j * km / steps / (111.3 * math.cos(math.radians(lat))), z))
    return out


def fetch(job):
    kind, z, x, y = job
    url, ext = SOURCES[kind]
    path = os.path.join(TEX, kind, str(z), str(x), f"{y}.{ext}")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return "cached"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # curl rather than urllib: python.org builds often lack a CA bundle.
    r = subprocess.run(["curl", "-sSfL", "-m", "120", "--retry", "3", "-A", UA, "-o", path, url.format(z=z, x=x, y=y)],
                       capture_output=True)
    if r.returncode != 0:
        if os.path.exists(path):
            os.remove(path)
        return "failed"
    return "fetched"


def write_manifest():
    m = {"dem": [], "sat": []}
    for kind, (_, ext) in SOURCES.items():
        root = os.path.join(TEX, kind)
        for dirpath, _, files in os.walk(root):
            for name in files:
                if name.endswith("." + ext):
                    z, x = os.path.relpath(dirpath, root).split(os.sep)
                    m[kind].append(f"{z}/{x}/{name.split('.')[0]}")
    with open(os.path.join(TEX, "manifest.json"), "w") as f:
        json.dump(m, f, separators=(",", ":"))
    return len(m["dem"]), len(m["sat"])


def main():
    ap = argparse.ArgumentParser(description="Prefetch 3D terrain tiles for a route.")
    ap.add_argument("origin"), ap.add_argument("destination")
    ap.add_argument("--corridor", type=int, default=2, help="tiles either side of the track at z7/z8 (default 2)")
    ap.add_argument("--jobs", type=int, default=16, help="parallel downloads (default 16)")
    args = ap.parse_args()

    (on, olat, olon), (dn, dlat, dlon) = airport(args.origin), airport(args.destination)
    print(f"{on} -> {dn}")
    pts = list(great_circle((olat, olon), (dlat, dlon)))
    want = set()
    for z, buf in ((5, 2), (6, 1), (7, args.corridor), (8, args.corridor)):
        for la, lo in pts:
            x, y = tile(la, lo, z)
            for dx in range(-buf, buf + 1):
                for dy in range(-buf, buf + 1):
                    want.add((z, (x + dx) % 2 ** z, y + dy))
    # Departure and arrival detail, for the 1 km and 500 m blocks near the ground.
    for lat, lon in ((olat, olon), (dlat, dlon)):
        want |= around(lat, lon, 150, 9) | around(lat, lon, 45, 10)
    want |= {(4, x, y) for x in range(16) for y in range(16)}          # a coarse world base
    jobs = [(kind, z, x, y) for (z, x, y) in sorted(want) for kind in ("sat", "dem") if not (kind == "dem" and z == 4)]
    print(f"{len(jobs)} tiles; downloading with {args.jobs} connections...")
    counts = {"cached": 0, "fetched": 0, "failed": 0}
    with ThreadPoolExecutor(args.jobs) as pool:
        for k, result in enumerate(pool.map(fetch, jobs), 1):
            counts[result] += 1
            if k % 100 == 0 or k == len(jobs):
                print(f"  {k}/{len(jobs)}  {counts}", flush=True)
    dem, sat = write_manifest()
    print(f"Done. Manifest: {dem} elevation and {sat} imagery tiles on disk."
          + (f" {counts['failed']} failed; run it again to retry." if counts["failed"] else ""))


if __name__ == "__main__":
    main()
