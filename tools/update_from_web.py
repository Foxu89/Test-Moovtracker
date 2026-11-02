#!/usr/bin/env python3
"""Scarica gli ZIP GTFS ACTV più recenti e rigenera fermate, linee e orari del sito.

Uso:  python3 tools/update_from_web.py CARTELLA_OUTPUT
Se i download sono rotti o incompleti NON modifica nulla (esce con errore).
Gli indirizzi si possono cambiare con le variabili AUT_URL e NAV_URL.
"""
import io, os, sys, tempfile, urllib.request, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_gtfs

AUT_URL = os.environ.get("AUT_URL", "https://actv.avmspa.it/sites/default/files/attachments/opendata/automobilistico/actv_aut.zip")
NAV_URL = os.environ.get("NAV_URL", "https://actv.avmspa.it/sites/default/files/attachments/opendata/navigazione/actv_nav.zip")
NEED = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt")

def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; TransitLiveUpdater/1.0)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    names = {os.path.basename(n) for n in z.namelist()}
    missing = [n for n in NEED if n not in names]
    if missing:
        sys.exit(f"ZIP incompleto da {url}: mancano {missing}")
    os.makedirs(dest)
    z.extractall(dest)
    print(f"scaricato {url} ({len(data)//1024} KB)")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        aut, nav = os.path.join(tmp, "aut"), os.path.join(tmp, "nav")
        fetch(AUT_URL, aut)
        fetch(NAV_URL, nav)
        # costruisce in una cartella temporanea e copia solo se tutto è andato bene
        stage = os.path.join(tmp, "out")
        os.makedirs(stage)
        build_gtfs.main(aut, nav, stage)
        import json, re
        txt = open(os.path.join(stage, "actv-data.js"), encoding="utf-8").read()
        data = json.loads(txt[txt.index("window.TL_DATA.venezia = ") + 25:].rstrip().rstrip(";"))
        if len(data["stops"]) < 500 or len(data["routes"]) < 20:
            sys.exit("Dati sospetti (troppo pochi): non aggiorno.")
        import shutil
        shutil.copy(os.path.join(stage, "actv-data.js"), os.path.join(out, "actv-data.js"))
        shutil.rmtree(os.path.join(out, "times"), ignore_errors=True)
        shutil.copytree(os.path.join(stage, "times"), os.path.join(out, "times"))
        print("OK: sito aggiornato.", data["valid"])
