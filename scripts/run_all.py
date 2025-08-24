# scripts/run_all.py
import os
import subprocess
import sys
from pathlib import Path
from shutil import copyfile

ROOT = Path(__file__).resolve().parents[1]
DP   = ROOT / "datapackage"
DATA = ROOT / "data"

STEPS = [
    ["python", "scripts/extract_exif.py", "--recursive", "--embed-full-exif", "--file-public", "false"],
    ["python", "scripts/build_deployments.py"],
    ["python", "scripts/link_media_by_serial.py"],
]

def die(msg: str, code: int = 1):
    print(f" {msg}")
    sys.exit(code)

def preflight():
    # ExifTool hint (not required if on PATH, but helpful)
    exiftool = os.getenv("EXIFTOOL_PATH", "")
    if not exiftool:
        print("ℹ EXIFTOOL_PATH is not set; relying on PATH or repo-local tools/exiftool/")
    # Data dir
    if not DATA.exists():
        die(f"Missing data directory: {DATA}")
    # Raw deployments sheet
    raw_dep = DP / "raw_deployment.csv"
    if not raw_dep.exists():
        die(f"Missing input: {raw_dep}")

def run_or_die(cmd: list[str]) -> None:
    print(f"\n>>> Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        die(f"Failed: {' '.join(cmd)}", proc.returncode)
    print("✅ Done")

def main():
    preflight()

    for cmd in STEPS:
        run_or_die(cmd)

    # Copy media_linked.csv → media.csv
    src = DP / "media_linked.csv"
    dst = DP / "media.csv"
    if not src.exists():
        die(f"Expected file not found: {src}")
    copyfile(src, dst)
    print(f"✅ Copied: {src} → {dst}")

    # Build observations and emit human-label template
    run_or_die(["python", "scripts/build_observations.py", "--emit-label-template"])

    print("\n All steps completed successfully!")
    print(" Annotate: datapackage/observations_to_label.csv")
    print(" Merge when ready: python scripts/merge_labels.py --inplace")

if __name__ == "__main__":
    main()
