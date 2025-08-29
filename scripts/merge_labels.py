# scripts/merge_labels.py
import csv
from pathlib import Path
import argparse
import sys
from datetime import datetime

# Fields that humans are allowed to edit (same as before)
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

# --- AI merge config ---
AI_DEFAULT_PATH = Path(__file__).parents[1] / "datapackage" / "detections_bioclip.csv"
AI_METHOD = "machine learning"
AI_CLASSIFIED_BY = "BioCLIP-2 zero-shot (multi-prompt)"
AI_CONTENT_FIELDS = {
    "observationType",              # blank|human|vehicle|animal
    "scientificName",               # optional (may be empty if not animal or below threshold)
    "classificationMethod",
    "classifiedBy",
    "classificationTimestamp",
    "classificationProbability",
    # bbox fields are not produced by BioCLIP; leave them blank
}

REQUIRED_OBS_FIELDS = [
    "observationID","deploymentID","mediaID","eventID",
    "eventStart","eventEnd",
    "observationLevel","observationType","cameraSetupType",
    "scientificName","count","lifeStage","sex","behavior",
    "individualID","individualPositionRadius","individualPositionAngle","individualSpeed",
    "bboxX","bboxY","bboxWidth","bboxHeight",
    "classificationMethod","classifiedBy","classificationTimestamp","classificationProbability",
    "observationTags","observationComments"
]

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r), list(r.fieldnames)

def validate_row(edits):
    # Minimal validation to avoid schema conflicts (human edits only)
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

def ensure_fields(obs_fields):
    """Ensure required observation fields exist; return possibly-extended list."""
    fields = list(obs_fields)
    for f in REQUIRED_OBS_FIELDS:
        if f not in fields:
            fields.append(f)
    return fields

def main():
    p = argparse.ArgumentParser(description="Merge human labels (priority) and AI descriptors into observations.csv")
    p.add_argument("--observations", default=str(Path(__file__).parents[1] / "datapackage" / "observations.csv"))
    p.add_argument("--labels", default=str(Path(__file__).parents[1] / "datapackage" / "observations_to_label.csv"))
    p.add_argument("--ai", default=str(AI_DEFAULT_PATH), help="AI detections CSV (e.g., detections_bioclip.csv)")
    p.add_argument("--ai-threshold", type=float, default=0.0, help="Min classificationProbability for AI to apply")
    p.add_argument("--out", default=str(Path(__file__).parents[1] / "datapackage" / "observations_merged.csv"))
    p.add_argument("--inplace", action="store_true", help="Overwrite observations.csv with merged result")
    args = p.parse_args()

    # Load observations
    obs_rows, obs_fields = load_csv(args.observations)
    obs_fields = ensure_fields(obs_fields)

    #  1) Apply HUMAN labels (priority)
    try:
        lab_rows, lab_fields = load_csv(args.labels)
    except FileNotFoundError:
        lab_rows, lab_fields = ([], [])
        print(f"[INFO] No human label file found at {args.labels}; skipping human merge.")

    # Index observations by observationID for human merge
    idx_by_oid = {r.get("observationID", ""): r for r in obs_rows}

    editable_present = [c for c in lab_fields if c in EDITABLE]
    updated_human = 0
    for lab in lab_rows:
        oid = lab.get("observationID", "").strip()
        if not oid or oid not in idx_by_oid:
            continue

        obs = idx_by_oid[oid]
        changed = {}
        for k in editable_present:
            v = (lab.get(k) or "").strip()
            if v == "":
                continue
            cur = (obs.get(k) or "").strip()

            if k == "observationType":
                v_norm = v.lower()
                cur_norm = cur.lower()
                # Ignore template default "unclassified" unless it's
                # actually changing a previously non-unclassified value.
                if v_norm == "unclassified" and cur_norm in ("", "unclassified"):
                    continue
                if v_norm == cur_norm:
                    continue
            else:
                if v == cur:
                    continue

            changed[k] = v

        if not changed:
            continue

        # Validate and apply real human edits
        try:
            validate_row(changed)
        except Exception as e:
            print(f"[WARN] Skipping {oid}: {e}")
            continue

        for k, v in changed.items():
            obs[k] = v

        # Mark classification as human ONLY when there was a real change
        cm = (obs.get("classificationMethod","") or "").strip().lower()
        if cm in ("", "machine learning"):
            obs["classificationMethod"] = "human"
            obs["classifiedBy"] = obs.get("classifiedBy") or "human"
            obs["classificationTimestamp"] = datetime.utcnow().isoformat(timespec="seconds")+"Z"

        updated_human += 1


    # ---- 2) Apply AI labels where fields are still empty (or were previously ML) ----
    ai_rows = []
    try:
        ai_rows, ai_fields = load_csv(args.ai)
    except FileNotFoundError:
        ai_rows = []
        print(f"[INFO] No AI file found at {args.ai}; skipping AI merge.")

    # Build index from mediaID -> best AI row (if multiples, keep highest prob)
    ai_by_media = {}
    for r in ai_rows:
        mid = (r.get("mediaID") or "").strip()
        if not mid:
            continue
        try:
            p = float((r.get("classificationProbability") or "0").strip())
        except Exception:
            p = 0.0
        # keep the highest-probability entry per mediaID
        prev = ai_by_media.get(mid)
        if prev is None or p > float((prev.get("classificationProbability") or "0")):
            ai_by_media[mid] = r

    updated_ai, skipped_lowconf, skipped_human_override, missing_ai = 0, 0, 0, 0
    for obs in obs_rows:
        mid = (obs.get("mediaID") or "").strip()
        if not mid:
            continue

        ai = ai_by_media.get(mid)
        if not ai:
            missing_ai += 1
            continue

        # parse AI probability
        try:
            ai_prob = float((ai.get("classificationProbability") or "0").strip())
        except Exception:
            ai_prob = 0.0

        if ai_prob < args.ai_threshold:
            skipped_lowconf += 1
            continue

        # Do NOT override human labels:
        # If classificationMethod is explicitly "human" (or any non-ML non-empty), skip AI
        cm = (obs.get("classificationMethod","") or "").strip().lower()
        if cm and cm != AI_METHOD:
            skipped_human_override += 1
            continue

        # Merge strategy: fill only empty fields OR fields that were previously set by machine learning
        def should_fill(field_name: str) -> bool:
            v = (obs.get(field_name) or "").strip()
            if not v:
                return True
            # allow ML to overwrite prior ML values; but never overwrite human-provided values
            return cm == AI_METHOD and field_name in ("observationType","scientificName",
                                                      "classificationMethod","classifiedBy",
                                                      "classificationTimestamp","classificationProbability")

        # Apply AI -> observation fields
        applied = False
        # observationType
        if should_fill("observationType"):
            val = (ai.get("observationType") or "").strip()
            if not val or val not in OBSERVATION_TYPE_ENUM:
                val = "unknown"
            obs["observationType"] = val
            applied = True

        # scientificName (optional)
        if should_fill("scientificName"):
            obs["scientificName"] = (ai.get("scientificName") or "").strip()
            # count/lifeStage/sex remain user-editable; leave blank

        # classification metadata
        if should_fill("classificationMethod"):
            obs["classificationMethod"] = AI_METHOD
        if should_fill("classifiedBy"):
            obs["classifiedBy"] = (ai.get("classifiedBy") or AI_CLASSIFIED_BY).strip() or AI_CLASSIFIED_BY
        if should_fill("classificationTimestamp"):
            obs["classificationTimestamp"] = datetime.utcnow().isoformat(timespec="seconds")+"Z"
        if should_fill("classificationProbability"):
            obs["classificationProbability"] = (ai.get("classificationProbability") or "").strip()

        if applied:
            updated_ai += 1

    # ---- Write output ----
    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=obs_fields)
        w.writeheader()
        w.writerows(obs_rows)

    print(f" Human-updated: {updated_human}")
    print(f" AI-filled    : {updated_ai}")
    print(f"  Skipped (low AI prob < {args.ai_threshold}) : {skipped_lowconf}")
    print(f"  Skipped (human override present)           : {skipped_human_override}")
    print(f"  Obs rows with no AI match                   : {missing_ai}")
    print(f"  Wrote merged file: {out_path}")

    if args.inplace:
        Path(args.observations).write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  Overwrote {args.observations} with merged content.")

if __name__ == "__main__":
    main()
