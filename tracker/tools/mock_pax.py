#!/usr/bin/env python3
"""A stand-in for the aircraft's Panasonic eXConnect server, for working on the ground.

Replays a recorded track (the tracker's data/<flight>/track.jsonl) through the same
endpoints the real server offers, at any speed:

    python3 tools/mock_pax.py data/<flight>/track.jsonl --from ZGHA --to EGLL --callsign CHH7963 --speed 30
    python3 server.py --pax 127.0.0.1:8099

Without a track file it flies a great circle between the two airports instead.
"""
import argparse
import json
import math
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))


def load_airports():
    with open(os.path.join(HERE, "..", "static", "airports.json"), encoding="utf-8") as f:
        d = json.load(f)
    out = {}
    for iata, icao, name, city, lat, lon in d["airports"]:
        for code in (icao, iata):
            if code:
                out.setdefault(code, (iata, icao, lat, lon))
    return out


def great_circle(a, b, n=600, gs=480, alt=38000):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    km = d * 6371.0
    pts, t = [], 0.0
    for i in range(n + 1):
        f = i / n
        A, B = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = A * math.cos(la1) * math.cos(lo1) + B * math.cos(la2) * math.cos(lo2)
        y = A * math.cos(la1) * math.sin(lo1) + B * math.cos(la2) * math.sin(lo2)
        z = A * math.sin(la1) + B * math.sin(la2)
        lat, lon = math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))
        climb = min(1, f * 20, (1 - f) * 12)          # climb out, cruise, descend
        pts.append({"t": t, "lat": lat, "lon": lon, "alt": round(alt * climb), "gs": round(gs * (0.5 + 0.5 * climb)), "hdg": 0})
        t += km / n / (gs * 1.852) * 3600
    for p, q in zip(pts, pts[1:]):
        dl = math.radians(q["lon"] - p["lon"])
        p1, p2 = math.radians(p["lat"]), math.radians(q["lat"])
        p["hdg"] = round(math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360)
    return pts


def main():
    ap = argparse.ArgumentParser(description="Replay a flight through a fake Panasonic server.")
    ap.add_argument("track", nargs="?", help="track.jsonl recorded by server.py (default: fly a great circle)")
    ap.add_argument("--from", dest="orig", default="ZGHA")
    ap.add_argument("--to", dest="dest", default="EGLL")
    ap.add_argument("--callsign", default="CHH7963")
    ap.add_argument("--tail", default="B-1135")
    ap.add_argument("--type", default="B787-9")
    ap.add_argument("--speed", type=float, default=30, help="replay speed multiplier (default 30x)")
    ap.add_argument("--start", type=float, default=0, help="start this fraction of the way through (0-1)")
    ap.add_argument("--port", type=int, default=8099)
    args = ap.parse_args()

    apts = load_airports()
    o, d = apts[args.orig], apts[args.dest]
    if args.track:
        with open(args.track) as f:
            pts = [json.loads(line) for line in f if line.strip()]
    else:
        pts = great_circle((o[2], o[3]), (d[2], d[3]))
    t0_rec, span = pts[0]["t"], pts[-1]["t"] - pts[0]["t"]
    started = time.time() - args.start * span / args.speed
    flight_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{args.callsign}-{args.orig}-{args.dest}"))

    def at_now():
        rt = t0_rec + min(span, (time.time() - started) * args.speed)
        i = next((k for k, p in enumerate(pts) if p["t"] >= rt), len(pts) - 1)
        return pts[i], (pts[-1]["t"] - rt)

    def v2():
        p, left = at_now()
        now = time.gmtime()
        return {
            "decompression_state": False, "weight_on_wheels": False, "all_doors_closed": True,
            "ground_speed_knots": p.get("gs"), "time_to_destination_minutes": round(left / 60),
            "wind_speed_knots": None, "flight_speed_mach": None, "true_heading_degree": p.get("hdg"),
            "current_utc_time": time.strftime("%H:%M", now), "outside_air_temp_celsius": None,
            "head_wind_speed_knots": None, "current_utc_date": time.strftime("%Y-%m-%d", now),
            "altitude_feet": p.get("alt"), "destination_icao": d[1], "departure_icao": o[1],
            "flight_number": args.callsign, "destination_iata": d[0], "departure_iata": o[0],
            "tail_number": args.tail, "flight_phase": "cruising", "time_at_origin": None,
            "time_at_destination": None, "estimated_arrival_time_utc": None,
            "takeoff_time_utc": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(started)),
            "current_coordinates": {"latitude": p["lat"], "longitude": p["lon"]},
            "aircraft_type": args.type, "flight_id": flight_id, "flight_state": "open",
            "passenger_anouncement": [], "weight_on_wheels_state": "air",
            "disclaimer": "Mock data from tools/mock_pax.py",
        }

    routes = {
        "/inflight/services/flightdata/v2/flightdata": v2,
        "/inflight/services/exconnect/v1/status": lambda: {"global_conn_enabled": True, "internet_connectivity_status": True,
                                                          "time_until_coverage_change": 0, "total_coverage_remaining": 0},
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            fn = routes.get(self.path.partition("?")[0])
            body = json.dumps(fn() if fn else {"error": {"code": 404, "message": "not in the mock"}}).encode()
            self.send_response(200 if fn else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    print(f"Mock Panasonic server on 127.0.0.1:{args.port}: {args.callsign} {o[0]} -> {d[0]}, "
          f"{len(pts)} points, {span / args.speed / 60:.1f} min at {args.speed}x", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
