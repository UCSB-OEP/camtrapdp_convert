import csv
import json
from pathlib import Path
import uuid
import argparse



REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "datapackage" / "media.csv"
OUT   = REPO / "datapackage" / "observations.csv"

def exif_to_event_id(row):
    """
    Try to derive a stable eventID from EXIF:
    - Prefer 'EventNumber' (Reconyx)
    - Else derive from 'Sequence' like '1 of 3' -> '1'
    Returns string like '<deploymentID>_ev<NNN>' or '' if not available.
    """
    exif_str = (row.get("exifData") or "").strip()
    if not exif_str:
        return ""
    try:
        exif = json.loads(exif_str)
    except Exception:
        return ""
    dep = (row.get("deploymentID") or "").strip()
    if not dep:
        return ""
    # Reconyx often has both:
    evn = exif.get("EventNumber")
    if isinstance(evn, int) or (isinstance(evn, str) and evn.strip().isdigit()):
        return f"{dep}_ev{str(evn).strip()}"
    seq = (exif.get("Sequence") or "").strip()  # e.g., "1 of 3"
    if seq and "of" in seq:
        first = seq.split("of")[0].strip()
        if first.isdigit():
            return f"{dep}_ev{first}"
    return ""

def main():
    parser = argparse.ArgumentParser(description="Build Camtrap DP observations.csv from media.csv")
    parser.add_argument(
        "--emit-label-template",
        action="store_true",
        help="Also write datapackage/observations_to_label.csv for human annotation"
    )
    parser.add_argument(
        "--media",
        default=str(MEDIA),
        help="Path to input media.csv"
    )
    parser.add_argument(
        "--out",
        default=str(OUT),
        help="Path to output observations.csv"
    )
    args = parser.parse_args()

    media_path = Path(args.media)
    out_path   = Path(args.out)

    if not media_path.exists():
        print(f"[ERROR] Not found: {media_path}")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect rows so we can write observations.csv and (optionally) the label template
    obs_rows = []
    tmpl_rows = []

    with media_path.open("r", encoding="utf-8") as fin:
        r = csv.DictReader(fin)
        n_in = 0
        for row in r:
            # skip totally blank lines
            if not any((row.get(k) or "").strip() for k in (r.fieldnames or [])):
                continue
            n_in += 1

            media_id = (row.get("mediaID") or "").strip()
            dep_id   = (row.get("deploymentID") or "").strip()
            ts       = (row.get("timestamp") or "").strip()
            filePath = (row.get("filePath") or "").strip()  # helpful context in the template

            if not media_id or not dep_id or not ts:
                # skip rows missing the essentials
                continue

            # Deterministic or random – you chose UUID earlier; keep that:
            obs_id = uuid.uuid4().hex[:8]

            # Optional eventID from EXIF (if available)
            event_id = exif_to_event_id(row)

            obs_rows.append({
                "observationID": obs_id,
                "deploymentID": dep_id,
                "mediaID": media_id,
                "eventID": event_id,
                "eventStart": ts,
                "eventEnd": ts,
                "observationLevel": "media",
                "observationType": "unclassified",
                "cameraSetupType": "",

                "scientificName": "",
                "count": "",
                "lifeStage": "",
                "sex": "",
                "behavior": "",
                "individualID": "",
                "individualPositionRadius": "",
                "individualPositionAngle": "",
                "individualSpeed": "",
                "bboxX": "",
                "bboxY": "",
                "bboxWidth": "",
                "bboxHeight": "",

                "classificationMethod": "",
                "classifiedBy": "",
                "classificationTimestamp": "",
                "classificationProbability": "",
                "observationTags": "",
                "observationComments": "",
            })

            # Minimal human-editable template row (context + editable fields)
            tmpl_rows.append({
                "observationID": obs_id,
                "mediaID":       media_id,
                "filePath":      filePath,
                "timestamp":     ts,
                # Editable fields:
                "observationType": "unclassified",  # animal|human|vehicle|blank|unknown|unclassified
                "scientificName": "",
                "count": "",
                "lifeStage": "",     # adult|subadult|juvenile
                "sex": "",           # female|male
                "behavior": "",
                "observationComments": "",
            })

    # 1) Write observations.csv
    with out_path.open("w", newline="", encoding="utf-8") as fout:
        w = csv.DictWriter(fout, fieldnames=[
            "observationID","deploymentID","mediaID","eventID",
            "eventStart","eventEnd",
            "observationLevel","observationType","cameraSetupType",
            "scientificName","count","lifeStage","sex","behavior",
            "individualID","individualPositionRadius","individualPositionAngle","individualSpeed",
            "bboxX","bboxY","bboxWidth","bboxHeight",
            "classificationMethod","classifiedBy","classificationTimestamp","classificationProbability",
            "observationTags","observationComments"
        ])
        w.writeheader()
        w.writerows(obs_rows)

    print(f" Wrote {out_path} ({len(obs_rows)} observations)")

    # 2) Optionally write the label template
    if args.emit_label_template:
        tmpl_path = out_path.parent / "observations_to_label.csv"
        if tmpl_rows:
            with tmpl_path.open("w", newline="", encoding="utf-8") as tf:
                tw = csv.DictWriter(tf, fieldnames=list(tmpl_rows[0].keys()))
                tw.writeheader()
                tw.writerows(tmpl_rows)
            print(f" Label template → {tmpl_path}")
        else:
            print("[WARN] No rows available to create observations_to_label.csv")


if __name__ == "__main__":
    main()
