import csv
from pathlib import Path
import argparse
import sys

EDITABLE = {
    "observationType",       # enum: animal|human|vehicle|blank|unknown|unclassified
    "scientificName",        # Latin name (free text)
    "count",                 # integer >=1
    "lifeStage",             # enum: adult|subadult|juvenile
    "sex",                   # enum: female|male
    "behavior",              # free text, pipe-separated
    "observationComments",   # free text
}

OBSERVATION_TYPE_ENUM = {"animal","human","vehicle","blank","unknown","unclassified"}
LIFESTAGE_ENUM = {"adult","subadult","juvenile"}
SEX_ENUM = {"female","male"}

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r), r.fieldnames

def validate_row(edits):
    # Minimal validation to avoid schema conflicts
    ot = edits.get("observationType", "").strip()
    if ot and ot not in OBSERVATION_TYPE_ENUM:
        raise ValueError(f"Invalid observationType: {ot}")

    ls = edits.get("lifeStage", "").strip()
    if ls and ls not in LIFESTAGE_ENUM:
        raise ValueError(f"Invalid lifeStage: {ls}")

    sx = edits.get("sex", "").strip()
    if sx and sx not in SEX_ENUM:
        raise ValueError(f"Invalid sex: {sx}")

    cnt = edits.get("count", "").strip()
    if cnt:
        try:
            c = int(cnt)
            if c < 1:
                raise ValueError("count must be >= 1")
        except Exception:
            raise ValueError(f"Invalid count (not integer): {cnt}")

def main():
    p = argparse.ArgumentParser(description="Merge human labels into observations.csv")
    p.add_argument("--observations", default=str(Path(__file__).parents[1] / "datapackage" / "observations.csv"))
    p.add_argument("--labels", default=str(Path(__file__).parents[1] / "datapackage" / "observations_to_label.csv"))
    p.add_argument("--out", default=str(Path(__file__).parents[1] / "datapackage" / "observations_merged.csv"))
    p.add_argument("--inplace", action="store_true", help="Overwrite observations.csv with merged result")
    args = p.parse_args()

    obs_rows, obs_fields = load_csv(args.observations)
    lab_rows, lab_fields = load_csv(args.labels)

    # Index observations by observationID
    idx = {r["observationID"]: r for r in obs_rows}

    # Which label fields will we read (intersection of EDITABLE with label columns)?
    editable_present = [c for c in lab_fields if c in EDITABLE]

    updated = 0
    for lab in lab_rows:
        oid = lab.get("observationID", "").strip()
        if not oid or oid not in idx:
            continue

        # Grab only editable fields from label row
        edits = {k: lab.get(k, "").strip() for k in editable_present if lab.get(k, "").strip() != ""}
        if not edits:
            continue

        # Validate before applying
        try:
            validate_row(edits)
        except Exception as e:
            print(f"[WARN] Skipping {oid}: {e}")
            continue

        # Apply edits
        obs = idx[oid]
        for k, v in edits.items():
            obs[k] = v
        updated += 1

    # Write merged file
    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=obs_fields)
        w.writeheader()
        w.writerows(obs_rows)

    print(f"✅ Merged labels into: {out_path} (updated {updated} observations)")

    if args.inplace:
        Path(args.observations).write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"✏️  Overwrote {args.observations} with merged content.")

if __name__ == "__main__":
    main()
