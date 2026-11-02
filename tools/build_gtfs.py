#!/usr/bin/env python3
"""Converte i GTFS statici ACTV in file leggeri per il sito.

Uso:  python3 build_gtfs.py CARTELLA_AUT CARTELLA_NAV CARTELLA_OUTPUT
      (le cartelle AUT/NAV sono gli ZIP scompattati)

Produce:
  CARTELLA_OUTPUT/actv-data.js          fermate, linee, calendari  (caricato all'avvio)
  CARTELLA_OUTPUT/times/actv-t-N.js     orari per fermata, a blocchi (caricati quando tocchi una fermata)
"""
import csv, json, sys, os, zlib, shutil
from collections import defaultdict

MODE = {"0": "tram", "1": "metro", "2": "train", "3": "bus", "4": "ferry"}
SHARDS = 24

def rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)

def minutes(t):
    t = (t or "").strip()
    if not t:
        return None
    h, m, *_ = t.split(":")
    return int(h) * 60 + int(m)

def main(aut, nav, out):
    folders = [(aut, "bus"), (nav, "ferry")]
    stops, routes, valid = [], {}, {}
    services, svc_index, exc = [], {}, []
    heads, head_index = [], {}
    shard_of = {}
    shards = [defaultdict(list) for _ in range(SHARDS)]

    def svc(sid):
        if sid not in svc_index:
            svc_index[sid] = len(services); services.append(sid)
        return svc_index[sid]

    def head(h):
        if h not in head_index:
            head_index[h] = len(heads); heads.append(h)
        return head_index[h]

    cal = {}
    for folder, mode in folders:
        for r in rows(os.path.join(folder, "stops.txt")):
            if not r["stop_lat"] or not r["stop_lon"]:
                continue
            sh = zlib.crc32(r["stop_id"].encode()) % SHARDS
            shard_of[r["stop_id"]] = sh
            stops.append([r["stop_id"], r["stop_name"].strip(), round(float(r["stop_lat"]), 6), round(float(r["stop_lon"]), 6), mode, sh])
        for r in rows(os.path.join(folder, "routes.txt")):
            routes[r["route_id"]] = [r["route_short_name"], r["route_long_name"].strip(),
                                     r["route_color"].upper(), r["route_text_color"].upper(), MODE.get(r["route_type"], "bus")]
        for r in rows(os.path.join(folder, "calendar.txt")):
            days = "".join(r[d] for d in ("monday","tuesday","wednesday","thursday","friday","saturday","sunday"))
            cal[r["service_id"]] = [days, r["start_date"], r["end_date"]]
        for r in rows(os.path.join(folder, "calendar_dates.txt")):
            exc.append([r["service_id"], r["date"], int(r["exception_type"])])
        try:
            fi = next(rows(os.path.join(folder, "feed_info.txt")))
            valid[os.path.basename(os.path.normpath(folder))] = [fi["feed_start_date"], fi["feed_end_date"]]
        except (StopIteration, FileNotFoundError):
            pass

    # corse: trip_id -> (route, headsign, service)
    trips = {}
    for folder, _ in folders:
        for r in rows(os.path.join(folder, "trips.txt")):
            trips[r["trip_id"]] = (r["route_id"], r["trip_headsign"].strip(), r["service_id"])

    # partenze: (stop, route, headsign, service) -> [minuti]
    groups = defaultdict(list)
    n = 0
    for folder, _ in folders:
        per_trip = defaultdict(list)
        for r in rows(os.path.join(folder, "stop_times.txt")):
            per_trip[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"], r["departure_time"] or r["arrival_time"],
                                           r["pickup_type"], r["stop_headsign"].strip()))
        for tid, lst in per_trip.items():
            if tid not in trips:
                continue
            route, th, sid = trips[tid]
            lst.sort()
            for i, (seq, stop, t, pickup, sh) in enumerate(lst):
                if i == len(lst) - 1 or pickup == "1":   # capolinea o solo discesa: niente partenza
                    continue
                m = minutes(t)
                if m is None:
                    continue
                groups[(stop, route, head(th or sh), svc(sid))].append(m)
                n += 1

    by_stop = defaultdict(list)
    for (stop, route, h, s), ms in groups.items():
        ms.sort()
        deltas = [ms[0]] + [b - a for a, b in zip(ms, ms[1:])]
        by_stop[stop].append([route, h, s, ",".join(map(str, deltas))])
    for stop, g in by_stop.items():
        shards[shard_of[stop]][stop] = g
    # fermate servite solo da tram -> modo "tram"
    for st in stops:
        ms = {routes[g[0]][4] for g in by_stop.get(st[0], []) if g[0] in routes}
        if ms == {"tram"}:
            st[4] = "tram"

    os.makedirs(os.path.join(out, "times"), exist_ok=True)
    for f in os.listdir(os.path.join(out, "times")):
        if f.startswith("actv-t-"):
            os.remove(os.path.join(out, "times", f))
    total = 0
    for i, sh in enumerate(shards):
        p = os.path.join(out, "times", f"actv-t-{i}.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f'TL_T({i},')
            json.dump(sh, f, ensure_ascii=False, separators=(",", ":"))
            f.write(");\n")
        total += os.path.getsize(p)

    data = {"stops": stops, "routes": routes, "valid": valid, "shards": SHARDS,
            "services": services, "heads": heads,
            "calendar": {svc_index[k]: v for k, v in cal.items() if k in svc_index},
            "exceptions": [[svc_index[s], d, t] for s, d, t in exc if s in svc_index],
            "credit": "Fermate, linee e orari: ACTV S.p.A. (licenza CC-BY)"}
    p = os.path.join(out, "actv-data.js")
    with open(p, "w", encoding="utf-8") as f:
        f.write("// Generato da tools/build_gtfs.py – non modificare a mano.\n")
        f.write("window.TL_DATA = window.TL_DATA || {};\nwindow.TL_DATA.venezia = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print(f"{len(stops)} fermate, {len(routes)} linee, {n} partenze")
    print(f"actv-data.js {os.path.getsize(p)//1024} KB · times/ {SHARDS} file, {total//1024} KB totali (~{total//SHARDS//1024} KB ciascuno)")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
