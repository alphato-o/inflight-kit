#!/usr/bin/env python3
"""Build static/airports.json from OurAirports (public domain).

    python3 tools/build_airports.py [airports.csv]

Without an argument it downloads https://davidmegginson.github.io/ourairports-data/airports.csv.
Keeps airports with scheduled service and an IATA code, keyed by both IATA and ICAO.
"""
import csv
import io
import json
import os
import sys
import urllib.request

SRC = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUT = os.path.join(os.path.dirname(__file__), "..", "static", "airports.json")


def main():
    if len(sys.argv) > 1:
        text = open(sys.argv[1], encoding="utf-8").read()
    else:
        text = urllib.request.urlopen(SRC, timeout=120).read().decode("utf-8")
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r["scheduled_service"] != "yes" or not r["iata_code"] or r["type"] not in ("large_airport", "medium_airport"):
            continue
        rows.append([r["iata_code"], r["icao_code"] or r["gps_code"], r["name"], r["municipality"],
                     round(float(r["latitude_deg"]), 4), round(float(r["longitude_deg"]), 4)])
    rows.sort()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"fields": ["iata", "icao", "name", "city", "lat", "lon"], "airports": rows}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"{len(rows)} airports -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
