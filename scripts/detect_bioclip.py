# scripts/detect_bioclip.py
import argparse
import csv
from pathlib import Path
from datetime import datetime

import pandas as pd
import torch
import open_clip
from PIL import Image, ImageOps

REPO = Path(__file__).resolve().parents[1]
MEDIA_CSV = REPO / "datapackage" / "media.csv"
OUT_CSV   = REPO / "datapackage" / "detections_bioclip.csv"

# Camera-trap tuned, multi-prompt labels (robust on night IR)
CLASS_PROMPTS = {
    "blank": [
        "an empty camera trap frame at night",
        "no animal or person visible in a camera trap image",
        "a blank infrared camera trap photo",
    ],
    "human": [
        "a person captured by a camera trap",
        "a human in a night infrared camera trap image",
        "a person walking past a camera trap",
    ],
    "vehicle": [
        "a vehicle captured by a camera trap",
        "a car or truck in a camera trap image",
        "a vehicle in a night infrared camera trap photo",
    ],
    "animal": [
        "a wild animal captured by a camera trap",
        "a mammal in a night infrared camera trap image",
        "wildlife in a camera trap photo at night",
    ],
}
CLASS_ORDER = ["blank", "human", "vehicle", "animal"]


def load_species_list(path: Path) -> list[str]:
    """Load species names from a .txt (one per line) or .csv (column named
    scientificName/species/name or the first column). Returns list of strings."""
    names: list[str] = []
    if not path.exists():
        return names
    if path.suffix.lower() == ".txt":
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s:
                names.append(s)
        return names

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        for col in ["scientificName", "species", "name"]:
            if col in df.columns:
                names = [str(x).strip() for x in df[col].dropna().tolist() if str(x).strip()]
                if names:
                    return names
        # fallback: first column
        first = df.columns[0]
        names = [str(x).strip() for x in df[first].dropna().tolist() if str(x).strip()]
        return names

    return names


def build_text_features(model, tokenizer, device, prompts_by_key: dict[str, list[str]]) -> tuple[torch.Tensor, list[str]]:
    """Average text features for each key over its prompt variants. Returns
    (features [K,d], keys in order)."""
    keys = list(prompts_by_key.keys())
    feats = []
    with torch.no_grad():
        for k in keys:
            toks = tokenizer(prompts_by_key[k]).to(device)
            f = model.encode_text(toks)
            f = f / f.norm(dim=-1, keepdim=True)
            feats.append(f.mean(dim=0, keepdim=True))
    return torch.cat(feats, dim=0), keys


def main():
    ap = argparse.ArgumentParser(description="Run BioCLIP zero-shot over media.csv")
    ap.add_argument("--limit", type=int, default=0, help="Process only first N images (0 = all)")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Device to run on")
    ap.add_argument("--autocontrast", action="store_true", help="Apply autocontrast (helps night/IR)")
    ap.add_argument("--species-file", type=str, default="", help="Path to .txt or .csv of candidate species names")
    ap.add_argument("--min-species-prob", type=float, default=0.40, help="Min prob to accept species name")
    args = ap.parse_args()

    if not MEDIA_CSV.exists():
        raise SystemExit(f"[ERROR] Not found: {MEDIA_CSV}. Run your pipeline to produce media.csv first.")

    # Load BioCLIP-2
    model, preprocess_train, preprocess_val = open_clip.create_model_and_transforms(
        "hf-hub:imageomics/bioclip-2"
    )
    tokenizer = open_clip.get_tokenizer("hf-hub:imageomics/bioclip-2")

    device = args.device if (args.device == "cuda" and torch.cuda.is_available()) else "cpu"
    model = model.to(device).eval()

  
    class_text_features, class_keys = build_text_features(model, tokenizer, device, CLASS_PROMPTS)
  
    order_idx = [class_keys.index(k) for k in CLASS_ORDER]
    class_text_features = class_text_features[order_idx, :]
    class_keys = CLASS_ORDER

    
    species_names: list[str] = []
    species_text_features: torch.Tensor | None = None
    if args.species_file:
        species_names = load_species_list(Path(args.species_file))
        if species_names:
            
            species_prompts = {
                name: [
                    f"a camera trap photo of {name}",
                    f"a wildlife image of {name}",
                    f"{name} in a night infrared camera trap image",
                ]
                for name in species_names
            }
            species_text_features, _ = build_text_features(model, tokenizer, device, species_prompts)

    # --- Load media
    df = pd.read_csv(MEDIA_CSV)
    need_cols = {"mediaID", "filePath"}
    if not need_cols.issubset(df.columns):
        raise SystemExit(f"[ERROR] media.csv must contain columns: {need_cols}")

    if args.limit > 0:
        df = df.iloc[: args.limit].copy()

    rows = []
    for _, row in df.iterrows():
        mid = str(row["mediaID"])
        fp  = str(row["filePath"])
        img_path = (REPO / fp).resolve() if not Path(fp).is_absolute() else Path(fp)
        if not Path(img_path).exists():
            continue

        try:
            img = Image.open(img_path).convert("RGB")
            if args.autocontrast:
                img = ImageOps.autocontrast(img, cutoff=2)
        except Exception:
            continue

        img_t = preprocess_val(img).unsqueeze(0).to(device)

        with torch.no_grad():
            # classify content (blank/human/vehicle/animal)
            img_feat = model.encode_image(img_t)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            logits_cls = 100.0 * (img_feat @ class_text_features.T)           # [1, 4]
            probs_cls  = logits_cls.softmax(dim=-1).squeeze(0).tolist()
            top_cls_idx = int(torch.tensor(probs_cls).argmax().item())
            obs_type = class_keys[top_cls_idx]
            obs_prob = float(probs_cls[top_cls_idx])

            # optional species if animal
            species_name = ""
            species_prob = ""
            if obs_type == "animal" and species_text_features is not None:
                logits_sp = 100.0 * (img_feat @ species_text_features.T)      # [1, S]
                probs_sp  = logits_sp.softmax(dim=-1).squeeze(0)
                sp_idx = int(torch.argmax(probs_sp).item())
                sp_prob = float(probs_sp[sp_idx].item())
                if sp_prob >= args.min_species_prob:
                    species_name = species_names[sp_idx]
                    species_prob = f"{sp_prob:.4f}"

        rows.append({
            "mediaID": mid,
            "filePath": fp,
           
            "observationType": obs_type,                 
            
            "classificationMethod": "machine learning",   
            "classifiedBy": "BioCLIP-2 zero-shot (multi-prompt)",
            "classificationProbability": f"{obs_prob:.4f}",
           
            "scientificName": species_name,
            "speciesProbability": species_prob,
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "mediaID","filePath",
            "observationType",
            "classificationMethod","classifiedBy","classificationProbability",
            "scientificName","speciesProbability",
        ])
        w.writeheader()
        w.writerows(rows)

    print(f" Wrote {OUT_CSV} with {len(rows)} rows at {datetime.utcnow().isoformat()}Z")


if __name__ == "__main__":
    main()
