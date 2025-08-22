import csv
import json
from pathlib import Path
from datetime import timezone
from dateutil import parser as dtparse  # pip install python-dateutil

REPO = Path(__file__).resolve().parents[1]
MEDIA_IN   = REPO / "datapackage" / "media.csv"
MEDIA_JSON = REPO / "datapackage" / "media_metadata.json"   # optional fallback
DEPLOY_CSV = REPO / "datapackage" / "deployments.csv"
MEDIA_OUT  = REPO / "datapackage" / "media_linked.csv"

def load_deployments_by_serial():
    """serial -> list of {deploymentID,start,end}"""
    idx = {}
    with DEPLOY_CSV.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            serial = (row.get("cameraID") or row.get("deviceID") or "").strip()
            if not serial:
                continue
            start = dtparse.parse(row["deploymentStart"]) if row.get("deploymentStart") else None
            end   = dtparse.parse(row["deploymentEnd"])   if row.get("deploymentEnd") else None
            idx.setdefault(serial, []).append({
                "deploymentID": row["deploymentID"],
                "start": start,
                "end": end
            })
    return idx

def index_media_json():
    """absolute file path -> EXIF dict (fallback if exifData column is empty)"""
    idx = {}
    if MEDIA_JSON.exists():
        data = json.loads(MEDIA_JSON.read_text(encoding="utf-8"))
        for item in data:
            idx[str(Path(item["file"]).resolve())] = item.get("metadata", {})
    return idx

def get_serial_from_media_row(row, fallback_by_abspath):
    # Prefer embedded exifData (Camtrap DP column)
    md = {}
    exif_str = (row.get("exifData") or "").strip()
    if exif_str:
        try:
            md = json.loads(exif_str)
        except Exception:
            md = {}
    # Fallback to media_metadata.json if needed
    if not md and fallback_by_abspath:
        abs_guess = str((REPO / row["filePath"]).resolve())
        md = fallback_by_abspath.get(abs_guess, {})
    # Common keys
    return (md.get("SerialNumber") or md.get("BodySerialNumber") or "").strip()

def parse_ts(row):
    t = (row.get("timestamp") or "").strip()
    if not t:
        return None
    dt = dtparse.parse(t)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def choose_deployment(cands, when):
    """If one candidate → choose it. If multiple → use time window. Else None."""
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]["deploymentID"]
    if when is None:
        return None
    for dep in cands:
        s, e = dep["start"], dep["end"]
        if (s is None or when >= s) and (e is None or when <= e):
            return dep["deploymentID"]
    return None

def main():
    print("[INFO] Loading deployments…")
    by_serial = load_deployments_by_serial()
    print(f"[INFO] Serials in deployments: {len(by_serial)}")

    print("[INFO] Indexing media JSON fallback (optional)…")
    meta_idx  = index_media_json()

    if not MEDIA_IN.exists():
        print(f"[ERROR] Not found: {MEDIA_IN}")
        return

    with MEDIA_IN.open("r", encoding="utf-8") as fin, MEDIA_OUT.open("w", newline="", encoding="utf-8") as fout:
        r = csv.DictReader(fin)
        w = csv.DictWriter(fout, fieldnames=r.fieldnames)
        w.writeheader()

        total, linked, warn_missing_serial, warn_ambiguous = 0, 0, 0, 0

        for row in r:
            total += 1
            # skip blank lines
            if not any((row.get(k) or "").strip() for k in (r.fieldnames or [])):
                continue

            serial = get_serial_from_media_row(row, meta_idx)
            when   = parse_ts(row)

            chosen = row.get("deploymentID","").strip()
            # Only (re)assign if missing or placeholder
            if not chosen or chosen.upper().startswith("DEPLOY"):
                cands = by_serial.get(serial, [])
                picked = choose_deployment(cands, when)
                if picked:
                    row["deploymentID"] = picked
                    linked += 1
                else:
                    if not serial:
                        warn_missing_serial += 1
                    elif len(cands) > 1:
                        warn_ambiguous += 1
                    # leave as-is 

            w.writerow(row)

    print(f" Linked {linked}/{total} media rows")
    if warn_missing_serial:
        print(f"   {warn_missing_serial} rows missing SerialNumber in EXIF")
    if warn_ambiguous:
        print(f"  {warn_ambiguous} rows same serial in multiple deployments; timestamp didn’t disambiguate")
    print(f"   Output: {MEDIA_OUT}")

if __name__ == "__main__":
    main()
