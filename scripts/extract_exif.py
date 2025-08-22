import os
import sys
import json
import csv
import argparse
import subprocess
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

def find_exiftool(user_path: str | None) -> str:
    # 1) explicit CLI flag
    if user_path:
        p = Path(user_path)
        if p.exists():
            return str(p)
        raise FileNotFoundError(f"exiftool not found at --exiftool '{user_path}'")

    # 2) environment variable
    env_path = os.getenv("EXIFTOOL_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    # 3) on PATH
    exe = shutil.which("exiftool") or shutil.which("exiftool.exe")
    if exe:
        return exe

    # 4) repo-local fallback: tools/exiftool/exiftool(.exe)
    repo_root = Path(__file__).resolve().parents[1]
    for cand in (
        repo_root / "tools" / "exiftool" / "exiftool.exe",
        repo_root / "tools" / "exiftool" / "exiftool",
    ):
        if cand.exists():
            return str(cand)

    # 5) fail with helpful message
    raise FileNotFoundError(
        "Could not find 'exiftool'. Install it and either:\n"
        " - add it to your PATH, or\n"
        " - set EXIFTOOL_PATH, or\n"
        " - put the binary at tools/exiftool/exiftool(.exe), or\n"
        " - pass --exiftool C:\\path\\to\\exiftool.exe"
    )


def parse_offset(tz_str, tz_num):
    """
    Return a datetime.tzinfo from EXIF timezone info:
    - tz_str like '+02:00'/'-09:00' (EXIF OffsetTimeOriginal)
    - tz_num like -9 / 2 (EXIF TimeZoneOffset)
    If none provided, return UTC (Z).
    """
    if tz_str and isinstance(tz_str, str):
        try:
            sign = 1 if tz_str.startswith("+") else -1
            hh, mm = tz_str[1:].split(":")
            return timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))
        except Exception:
            pass
    if tz_num is not None:
        try:
            # EXIF may give an int or list; handle both
            if isinstance(tz_num, list) and tz_num:
                tz_num = tz_num[0]
            hours = int(tz_num)
            return timezone(timedelta(hours=hours))
        except Exception:
            pass
    return timezone.utc  # default to UTC if unknown

def to_iso_zoned(dt_exif: str | None, offset_time: str | None, tz_num) -> str:
    """
    Convert 'YYYY:MM:DD HH:MM:SS' plus optional offset to ISO8601 with TZ.
    If dt_exif is None, return empty string.
    """
    if not dt_exif:
        return ""
    # Parse EXIF time
    dt = datetime.strptime(dt_exif, "%Y:%m:%d %H:%M:%S")
    tz = parse_offset(offset_time, tz_num)
    dt = dt.replace(tzinfo=tz)
    # Format to ISO 8601
    if dt.utcoffset() == timedelta(0):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Python prints offsets as ±HHMM; convert to ±HH:MM
    s = dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    return s[:-2] + ":" + s[-2:]

def mimetype_for(path: Path, exif_mime: str | None) -> str:
    if exif_mime and "/" in exif_mime:
        return exif_mime
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
    }.get(ext, "image/jpeg")

def capture_method_from_exif(md: dict) -> str:
    trig = (md.get("TriggerMode") or md.get("Trigger") or "").lower()
    if "motion" in trig or "activity" in trig:
        return "activityDetection"
    if "time" in trig and "lapse" in trig:
        return "timeLapse"
    return ""  # optional field: empty is OK

def extract_exif(exiftool_path: str, image_path: Path) -> dict:
    result = subprocess.run([exiftool_path, "-json", str(image_path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"exiftool failed for {image_path} → {result.stderr}")
    data = json.loads(result.stdout)
    if not data:
        raise ValueError(f"No EXIF data returned for {image_path}")
    return data[0]

def iter_media(root: Path, recursive: bool) -> list[Path]:
    exts = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    files = []
    walker = root.rglob if recursive else root.glob
    for pat in exts:
        files.extend(walker(pat))
    return sorted({p.resolve() for p in files})

def main():
    parser = argparse.ArgumentParser(description="Write Camtrap DP-compliant media.csv from image EXIF.")
    parser.add_argument("--data-dir", default=str(Path(__file__).parent.parent / "data"))
    parser.add_argument("--out-media", default=str(Path(__file__).parent.parent / "datapackage" / "media.csv"))
    parser.add_argument("--out-json", default=str(Path(__file__).parent.parent / "datapackage" / "media_metadata.json"))
    parser.add_argument("--deployment-id", default="DEPLOY1")
    parser.add_argument("--exiftool", default=None)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--file-public", default="false", choices=["true", "false"], help="Required by schema; default false")
    parser.add_argument("--embed-full-exif", action="store_true", help="Store the full EXIF object in exifData")
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    out_media = Path(args.out_media).resolve()
    out_json = Path(args.out_json).resolve()
    file_public = True if args.file_public.lower() == "true" else False

    if not data_dir.exists():
        print(f"[ERROR] --data-dir not found: {data_dir}")
        sys.exit(1)

    try:
        exiftool_path = find_exiftool(args.exiftool)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    media_files = iter_media(data_dir, args.recursive)
    if not media_files:
        print(f"[WARN] No media found in {data_dir}.")
        sys.exit(0)

    out_media.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    all_raw = []
    with out_media.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "mediaID",
                "deploymentID",
                "captureMethod",
                "timestamp",
                "filePath",
                "filePublic",
                "fileName",
                "fileMediatype",
                "exifData",
                "favorite",
                "mediaComments",
            ],
        )
        writer.writeheader()

        for p in media_files:
            try:
                md = extract_exif(exiftool_path, p)

                # Timestamp with time zone
                dt_exif = md.get("DateTimeOriginal") or md.get("CreateDate")
                offset_time = md.get("OffsetTimeOriginal")  # e.g. "-09:00"
                tz_num = md.get("TimeZoneOffset")           # e.g. -9 or [ -9, -9 ]
                iso_ts = to_iso_zoned(dt_exif, offset_time, tz_num)

                # filePath as posix (forward slashes) and relative if possible
                repo_root = Path(__file__).parent.parent.resolve()
                try:
                    rel = p.resolve().relative_to(repo_root).as_posix()
                except Exception:
                    rel = p.resolve().as_posix()

                # fileName & mediatype
                file_name = p.name
                file_mime = mimetype_for(p, md.get("MIMEType"))

                # captureMethod
                capture_method = capture_method_from_exif(md)

                # exifData: embed full EXIF or a small subset
                exif_obj = md if args.embed_full_exif else {
                    "Make": md.get("Make"),
                    "Model": md.get("Model"),
                    "TriggerMode": md.get("TriggerMode"),
                    "GPSLatitude": md.get("GPSLatitude"),
                    "GPSLongitude": md.get("GPSLongitude"),
                }
                exif_json = json.dumps(exif_obj, ensure_ascii=False)

                

                row = {
                   #"mediaID": Path(file_name).stem, #Can be used for a short ID, but may not be unique
                   # "mediaID": f"{Path(file_name).stem}_{uuid.uuid4().hex[:8]}", Or combine with a UUID for uniqueness
                   "mediaID": uuid.uuid4().hex[:8],   # short unique ID   
                    "deploymentID": args.deployment_id,
                    "captureMethod": capture_method or "",
                    "timestamp": iso_ts,
                    "filePath": rel,
                    "filePublic": "true" if file_public else "false",
                    "fileName": file_name,
                    "fileMediatype": file_mime,
                    "exifData": exif_json,
                    "favorite": "",
                    "mediaComments": "",
                }

                writer.writerow(row)
                all_raw.append({"file": str(p), "metadata": md})

            except Exception as e:
                print(f"[WARN] Skipping {p} → {e}")

    with out_json.open("w", encoding="utf-8") as jf:
        json.dump(all_raw, jf, indent=2)

    print(" media.csv written in Camtrap DP shape.")
    print(f"   Rows: {len(all_raw)}")
    print(f"   CSV : {out_media}")
    print(f"   JSON: {out_json}")

if __name__ == "__main__":
    main()
