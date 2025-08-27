# scripts/run_all.py
import os
import subprocess
import sys
from pathlib import Path
from shutil import copyfile

# repo root + standard locations
ROOT = Path(__file__).resolve().parents[1]
DP   = ROOT / "datapackage"

# I prefer to keep raw media outside the repo to avoid Defender/OneDrive issues.
# If CAMTRAP_DATA_DIR is set, use it; otherwise default to repo/data.
DATA = Path(os.getenv("CAMTRAP_DATA_DIR", str(ROOT / "data"))).resolve()

# If I already set EXIFTOOL_PATH in my env, use it; otherwise let extract_exif.py discover it.
EXIFTOOL = os.getenv("EXIFTOOL_PATH", "").strip()

# If EXIFTOOL_PATH is a directory, assume the binary is inside it.
# This makes it robust for folks who unzip exiftool and set the folder path.
if EXIFTOOL:
    p = Path(EXIFTOOL)
    if p.is_dir():
        for name in ("exiftool.exe", "exiftool"):  # win + *nix
            cand = p / name
            if cand.exists():
                EXIFTOOL = str(cand)
                break  # stop at the first match

def die(msg: str, code: int = 1) -> None:
    print(f" {msg}")
    sys.exit(code)

def run_or_die(cmd: list[str]) -> None:
    # Always run from repo root so all relative paths behave
    print(f"\n>>> Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        die(f"Failed: {' '.join(cmd)}", proc.returncode)
    print(" Done")

def preflight() -> None:
    print("=== Preflight ===")
    print(f"- Using Python      : {sys.executable}")
    print(f"- Repo root         : {ROOT}")
    print(f"- Data dir          : {DATA} {'(exists)' if DATA.exists() else '(MISSING!)'}")
    print(f"- datapackage dir   : {DP}")

    if EXIFTOOL:
        print(f"- EXIFTOOL_PATH     : {EXIFTOOL}")
        if not Path(EXIFTOOL).exists():
            die(f"EXIFTOOL_PATH is set but not found: {EXIFTOOL}\n"
                f"Hint: set EXIFTOOL_PATH to the *binary*, e.g. C:\\path\\to\\exiftool.exe")
    else:
        print("- EXIFTOOL_PATH     : (not set; extract_exif.py will search PATH/env/repo tools)")

    # I require the raw deployments sheet since build_deployments uses it
    raw_dep = DP / "raw_deployment.csv"
    if not raw_dep.exists():
        die(f"Missing input: {raw_dep}")

    if not DATA.exists():
        die(f"Missing data directory: {DATA}")

def build_steps() -> list[list[str]]:
    # I explicitly pass --data-dir (and --exiftool when available)
    extract_cmd = [
        sys.executable, "scripts/extract_exif.py",
        "--data-dir", str(DATA),
        "--recursive",
        "--embed-full-exif",
        "--file-public", "false",
    ]
    if EXIFTOOL:
        extract_cmd += ["--exiftool", EXIFTOOL]

    return [
        extract_cmd,
        [sys.executable, "scripts/build_deployments.py"],
        [sys.executable, "scripts/link_media_by_serial.py"],
    ]

def main() -> None:
    preflight()

    # First pass: extract → deployments → link
    for cmd in build_steps():
        run_or_die(cmd)

    # After linking, I expect media_linked.csv to exist; copy over media.csv
    src = DP / "media_linked.csv"
    dst = DP / "media.csv"
    if not src.exists():
        die(f"Expected file not found: {src}")
    copyfile(src, dst)
    print(f"✅ Copied: {src} → {dst}")

    # Build observations and emit a human-label template in one go
    run_or_die([sys.executable, "scripts/build_observations.py", "--emit-label-template"])

    print("\n All steps completed successfully!")
    print(" Annotate: datapackage/observations_to_label.csv")
    print(" Merge when ready: python scripts/merge_labels.py --inplace")

if __name__ == "__main__":
    main()
