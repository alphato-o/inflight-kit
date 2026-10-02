#!/usr/bin/env python3
"""In-flight tracker backend.

Polls the aircraft's Panasonic eXConnect server (reachable on the cabin Wi-Fi even
while the satellite link is down), measures real internet reachability over the
Wi-Fi interface (bypassing any local proxy such as Surge), keeps a per-flight track
log, and serves the 2D chart (/) and the 3D voxel view (/3d/).

    python3 server.py                 # then open http://127.0.0.1:7963
    python3 server.py --pax 172.19.248.2 --dns 172.19.248.1   # skip auto-discovery
    python3 server.py --pax 127.0.0.1:8099                     # with tools/mock_pax.py, on the ground

Everything it needs at flight time is local; run tools/prefetch_tiles.py on the
ground first if you want 3D terrain for the route.
"""
import argparse
import http.client
import json
import os
import random
import re
import socket
import struct
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DATA = os.path.join(HERE, "data")

PAX_HOST = "services.inflightpanasonic.aero"
POLL_S = 3
PROBE_S = 15
RAW_EVERY_S = 10
IP_BOUND_IF = 25                 # macOS socket option: pin a socket to one interface
# Probe targets reachable from cabin networks that route through China as well as
# everywhere else. Cache-busted paths, because portals fake the usual check URLs.
PROBE_TARGETS = [("www.baidu.com", "/robots.txt"), ("connect.rom.miui.com", "/generate_204")]
RAW_ENDPOINTS = [
    "/flightdata/v2/flightdata", "/flightdata/v1/flightdata", "/exconnect/v1/status",
    "/exconnect/v1/wisp_product_info", "/airport_info/v1/multi_airport_info",
    "/connecting_gate/v1/connecting_gate_info", "/extv_metadata/v1/commissioning_status",
    "/extv_metadata/v1/station_status", "/extv_metadata/v1/stations", "/maps/v1/flight_map",
]
# ICAO -> IATA airline designators, to show "HU7963" rather than "CHH7963".
AIRLINES = {
    "CHH": "HU", "CCA": "CA", "CES": "MU", "CSN": "CZ", "CXA": "MF", "CSC": "3U", "CDG": "SC",
    "CHB": "PN", "CBJ": "JD", "CQH": "9C", "CPA": "CX", "HDA": "KA", "BAW": "BA", "VIR": "VS",
    "DLH": "LH", "AFR": "AF", "KLM": "KL", "FIN": "AY", "SAS": "SK", "UAE": "EK", "QTR": "QR",
    "ETD": "EY", "SIA": "SQ", "JAL": "JL", "ANA": "NH", "KAL": "KE", "AAR": "OZ", "EVA": "BR",
}

cfg = argparse.Namespace(pax_ip=None, pax_port=80, dns=None, iface="en0")
lock = threading.Lock()
state = {"flight": None, "flight_at": None, "flight_error": None, "exconnect": None,
         "probe": {"ok": None, "rtt_ms": None, "surge_ms": None, "at": None, "history": []},
         "online": None, "flight_key": None}
track, events, raw = [], [], {}
airports = {}


# ---------------------------------------------------------------- discovery

def gateway(iface):
    """Default router on the Wi-Fi interface (macOS), e.g. 172.19.248.1."""
    try:
        out = subprocess.run(["ipconfig", "getoption", iface, "router"], capture_output=True, text=True, timeout=5)
        ip = out.stdout.strip()
        return ip if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) else None
    except (OSError, subprocess.SubprocessError):
        return None


dns_cache = {}


def resolve(host, server=None):
    """A-record lookup sent straight to the cabin resolver, so a local proxy's fake IPs never leak in."""
    server = server or cfg.dns
    if not server:
        return None
    q = struct.pack(">HHHHHH", random.randint(0, 65535), 0x0100, 1, 0, 0, 0)
    q += b"".join(bytes([len(p)]) + p.encode() for p in host.split(".")) + b"\0" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    try:
        s.sendto(q, (server, 53))
        r = s.recv(1500)
        an, i = struct.unpack(">H", r[6:8])[0], len(q)
        for _ in range(an):
            i += 2 if r[i] & 0xC0 == 0xC0 else r[i:].index(0) + 1
            rtype, _, _, rdlen = struct.unpack(">HHIH", r[i:i + 10])
            i += 10
            if rtype == 1 and rdlen == 4:
                dns_cache[host] = socket.inet_ntoa(r[i:i + 4])
                break
            i += rdlen
    except OSError:
        pass
    finally:
        s.close()
    return dns_cache.get(host)


def discover():
    """Find the cabin DNS and the on-board Panasonic server, unless given on the command line."""
    if not cfg.dns:
        cfg.dns = gateway(cfg.iface)
    if not cfg.pax_ip and cfg.dns:
        cfg.pax_ip = resolve(PAX_HOST)
    return cfg.pax_ip


# ---------------------------------------------------------------- per-flight storage

def flight_key(d):
    """One folder per flight: the feed's flight_id, else date + callsign."""
    fid = d.get("flight_id")
    if fid:
        return re.sub(r"[^A-Za-z0-9_-]", "", fid)
    return f"{d.get('current_utc_date', 'unknown')}_{d.get('flight_number', 'flight')}"


def paths(key):
    folder = os.path.join(DATA, key)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "track.jsonl"), os.path.join(folder, "events.jsonl")


def switch_flight(key):
    """Called with the lock held when the aircraft reports a different flight."""
    track.clear()
    events.clear()
    state["flight_key"] = key
    for path, sink in zip(paths(key), (track, events)):
        if os.path.exists(path):
            with open(path) as f:
                sink.extend(json.loads(line) for line in f if line.strip())
    state["online"] = events[-1]["type"] == "link_up" if events else None


def append(kind, obj):
    track_path, events_path = paths(state["flight_key"])
    with open(track_path if kind == "track" else events_path, "a") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------- polling

def pax_request(path):
    if not cfg.pax_ip and not discover():
        raise RuntimeError("on-board server not found (not on a Panasonic cabin network?)")
    conn = http.client.HTTPConnection(cfg.pax_ip, cfg.pax_port, timeout=6)
    try:
        conn.request("GET", "/inflight/services" + path, headers={"Host": PAX_HOST})
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", "replace")
    finally:
        conn.close()


def pax_get(path):
    status, text = pax_request(path)
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    return json.loads(text)


def poll_flight():
    while True:
        try:
            d = pax_get("/flightdata/v2/flightdata")
            now = time.time()
            c = d.get("current_coordinates") or {}
            lat, lon = c.get("latitude"), c.get("longitude")
            with lock:
                key = flight_key(d)
                if key != state["flight_key"]:
                    switch_flight(key)
                state["flight"], state["flight_at"], state["flight_error"] = d, now, None
                last = track[-1] if track else None
                if lat is not None and (not last or (last["lat"], last["lon"]) != (lat, lon)):
                    pt = {"t": round(now, 1), "lat": lat, "lon": lon,
                          "alt": d.get("altitude_feet"), "gs": d.get("ground_speed_knots"),
                          "hdg": d.get("true_heading_degree"), "online": state["online"]}
                    track.append(pt)
                    append("track", pt)
        except Exception as e:
            with lock:
                state["flight_error"] = str(e)
        time.sleep(POLL_S)


def poll_raw():
    """Every endpoint the on-board server offers, kept verbatim (including its errors)."""
    while True:
        for path in RAW_ENDPOINTS:
            try:
                status, text = pax_request(path)
                try:
                    body = json.loads(text)
                except ValueError:
                    body = text.strip()
                entry = {"status": status, "body": body}
            except Exception as e:
                entry = {"status": None, "body": None, "error": str(e)}
            entry["at"] = time.time()
            with lock:
                raw[path] = entry
        time.sleep(RAW_EVERY_S)


def probe_direct():
    """Real HTTP round trip over the Wi-Fi interface, bypassing any local proxy. Returns ms, or None.

    Satellite accelerators answer TCP handshakes locally in a few ms whether or not the
    satellite is up, so we time the response to a cache-busted request instead.
    """
    try:
        idx = socket.if_nametoindex(cfg.iface)
    except OSError:
        return None
    for host, path in PROBE_TARGETS:
        ip = resolve(host)
        if not ip:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, idx)
        s.settimeout(12)
        try:
            s.connect((ip, 80))
            t0 = time.monotonic()
            req = f"GET {path}?n={random.getrandbits(40)} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
            s.sendall(req.encode())
            if s.recv(16).startswith(b"HTTP/"):
                return (time.monotonic() - t0) * 1000
        except OSError:
            continue
        finally:
            s.close()
    return None


def probe_system_route():
    """HTTP round trip to Google along the normal system route (through Surge or a VPN, if any)."""
    t0 = time.monotonic()
    conn = http.client.HTTPConnection("www.google.com", timeout=15)
    try:
        conn.request("GET", "/generate_204")
        if conn.getresponse().status == 204:
            return (time.monotonic() - t0) * 1000
    except Exception:
        pass
    finally:
        conn.close()
    return None


def poll_link():
    fails = 0
    while True:
        rtt, surge = probe_direct(), probe_system_route()
        try:
            ex = pax_get("/exconnect/v1/status")
        except Exception:
            ex = None
        now = time.time()
        fails = 0 if rtt is not None else fails + 1
        r = lambda v: None if v is None else round(v)
        with lock:
            p = state["probe"]
            p.update(ok=rtt is not None, rtt_ms=r(rtt), surge_ms=r(surge), at=now)
            p["history"] = (p["history"] + [[round(now), r(rtt), r(surge)]])[-240:]
            state["exconnect"] = ex
            # Debounce: one lost probe on a satellite link is noise, two in a row is an outage.
            online = state["online"]
            if rtt is not None and online is not True:
                online = True
            elif fails >= 2 and online is not False:
                online = False
            if online != state["online"] and state["flight_key"]:
                ev = {"t": round(now, 1), "type": "link_up" if online else "link_down"}
                if track:
                    ev.update(lat=track[-1]["lat"], lon=track[-1]["lon"])
                events.append(ev)
                append("events", ev)
            state["online"] = online
        time.sleep(PROBE_S)


# ---------------------------------------------------------------- route

def load_airports():
    try:
        with open(os.path.join(STATIC, "airports.json"), encoding="utf-8") as f:
            d = json.load(f)
    except OSError:
        return
    for iata, icao, name, city, lat, lon in d["airports"]:
        city = re.sub(r"\s*\(.*\)$", "", city or "") or name
        entry = {"iata": iata, "icao": icao, "name": name, "city": city, "lat": lat, "lon": lon}
        for code in (icao, iata):
            if code:
                airports.setdefault(code, entry)


def airport(icao, iata):
    """ICAO first: the feed's IATA codes can be legacy ones (Changsha appears as HHA, not CSX)."""
    a = (icao and airports.get(icao)) or (iata and airports.get(iata))
    if not a:
        return None
    return dict(a, code=iata or a["iata"])


def route():
    f = state["flight"] or {}
    callsign = f.get("flight_number") or ""
    m = re.match(r"([A-Z]{3})(\d+[A-Z]?)$", callsign)
    flight = (AIRLINES.get(m.group(1), m.group(1)) + m.group(2)) if m else callsign
    return {"origin": airport(f.get("departure_icao"), f.get("departure_iata")),
            "dest": airport(f.get("destination_icao"), f.get("destination_iata")),
            "callsign": callsign, "flight": flight, "tail": f.get("tail_number"),
            "type": f.get("aircraft_type"), "takeoff": f.get("takeoff_time_utc"), "flight_key": state["flight_key"]}


# ---------------------------------------------------------------- HTTP

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        # Always revalidate, so a reload picks up edits to the pages.
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, obj):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/api/state":
            with lock:
                return self.send_json(dict(state, server_time=time.time(), events=events[-50:], track_len=len(track)))
        if path == "/api/route":
            with lock:
                return self.send_json(route())
        if path == "/api/raw":
            with lock:
                return self.send_json(dict(raw))
        if path == "/api/track":
            since = 0.0
            for kv in query.split("&"):
                if kv.startswith("since="):
                    since = float(kv[6:] or 0)
            with lock:
                return self.send_json([p for p in track if p["t"] > since])
        return super().do_GET()


class Server(ThreadingHTTPServer):
    request_queue_size = 256   # the 3D view requests dozens of tiles at once
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 7963)))
    ap.add_argument("--pax", default=os.environ.get("PAX"), help="on-board Panasonic server, host[:port] (default: resolve %s via the cabin DNS)" % PAX_HOST)
    ap.add_argument("--dns", default=os.environ.get("PAX_DNS"), help="cabin DNS server (default: the Wi-Fi gateway)")
    ap.add_argument("--iface", default=os.environ.get("IFACE", "en0"), help="Wi-Fi interface (default en0)")
    args = ap.parse_args()
    if args.pax:
        host, _, port = args.pax.partition(":")
        cfg.pax_ip, cfg.pax_port = host, int(port or 80)
    cfg.dns, cfg.iface = args.dns, args.iface
    os.makedirs(DATA, exist_ok=True)
    load_airports()
    found = discover()
    for fn in (poll_flight, poll_link, poll_raw):
        threading.Thread(target=fn, daemon=True).start()
    print(f"Tracker on http://127.0.0.1:{args.port}  (3D view at /3d/)", flush=True)
    print(f"  cabin DNS {cfg.dns or 'not found'}, on-board server {found or 'not found yet, will keep looking'}", flush=True)
    Server(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
