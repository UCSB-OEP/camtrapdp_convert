import csv
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parents[1]
RAW  = REPO / "datapackage" / "raw_deployment.csv"
OUT  = REPO / "datapackage" / "deployments.csv"

TZ_ABBR_TO_OFFSET = {
    "UTC": "Z", "Z": "Z",
    "EST": "-05:00", "EDT": "-04:00",
    "CST": "-06:00", "CDT": "-05:00",
    "MST": "-07:00", "MDT": "-06:00",
    "PST": "-08:00", "PDT": "-07:00",
}

def normalize_offset(val: str | None, header_hint: str | None, default_hint: str = "EST") -> str:
    if val and val.strip():
        v = val.strip().upper()
        if v == "Z": return "Z"
        if len(v) == 6 and v[0] in "+-" and v[1:3].isdigit() and v[3] == ":" and v[4:6].isdigit():
            return v
        if v in TZ_ABBR_TO_OFFSET:
            return TZ_ABBR_TO_OFFSET[v]
        return v
    if header_hint:
        h = header_hint.strip().upper()
        if h in TZ_ABBR_TO_OFFSET:
            return TZ_ABBR_TO_OFFSET[h]
    h = default_hint.strip().upper()
    return TZ_ABBR_TO_OFFSET.get(h, "Z")

def parse_date(s: str | None) -> datetime | None:
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt)
            return datetime(d.year, d.month, d.day, 0, 0, 0)
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date format: {s}")

def parse_time(s: str | None):
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(s, fmt)
            return (t.hour, t.minute, getattr(t, "second", 0))
        except ValueError:
            pass
    raise ValueError(f"Unrecognized time format: {s}")

def combine_dt(d: datetime | None, hms, end_of_day_if_none=False):
    if d is None:
        return None
    if hms:
        h, m, s = hms
        return d.replace(hour=h, minute=m, second=s)
    return d.replace(hour=23, minute=59, second=59) if end_of_day_if_none else d

def iso_with_offset(dt: datetime | None, offset: str) -> str:
    if dt is None:
        return ""
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return base + ("Z" if offset == "Z" else offset)

def normalize_bool(val: str | None) -> str:
    if val is None: return ""
    v = val.strip().lower()
    if v in ("true","t","yes","y","1"):  return "true"
    if v in ("false","f","no","n","0"):  return "false"
    return ""

def normalize_camera_model(m: str | None) -> str:
    if not m: return ""
    m = m.strip()
    if "HF2" in m.upper() or "HYPERFIRE" in m.upper():
        return f"Reconyx-{m}"
    return m

def safe_num(s: str | None) -> str:
    return s.strip() if s and s.strip() else ""

def main():
    print(f"[INFO] RAW : {RAW}")
    print(f"[INFO] OUT : {OUT}")
    if not RAW.exists():
        print(f"[ERROR] Not found: {RAW}")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)

    with RAW.open("r", encoding="utf-8-sig") as f_in, OUT.open("w", newline="", encoding="utf-8") as f_out:
        r = csv.DictReader(f_in)
        if not r.fieldnames:
            print("[ERROR] No header row found in RAW.")
            return

        # detect an 'EndTime ...' header and pull TZ hint (e.g., 'EndTime EST')
        end_time_header = None
        tz_hint_from_header = None
        for h in r.fieldnames:
            if h and "endtime" in h.replace(" ", "").lower():
                end_time_header = h
                parts = h.split()
                if len(parts) >= 2:
                    tz_hint_from_header = parts[-1]
                break

        print("[INFO] Headers:", r.fieldnames)
        print("[INFO] EndTime header:", end_time_header, "TZ hint:", tz_hint_from_header)

        w = csv.DictWriter(
            f_out,
            fieldnames=[
                "deploymentID","locationID","locationName","latitude","longitude","coordinateUncertainty",
                "deploymentStart","deploymentEnd","setupBy","cameraID","cameraModel",
                "cameraDelay","cameraHeight","cameraDepth","cameraTilt","cameraHeading","detectionDistance",
                "timestampIssues","baitUse","featureType","habitat","deploymentGroups","deploymentTags","deploymentComments",
            ],
        )
        w.writeheader()

        written = 0
        for i, row in enumerate(r, start=1):
            # skip fully blank lines
            if not any((row.get(k) or "").strip() for k in r.fieldnames):
                continue

            siteID   = (row.get("siteID") or "").strip()
            serial   = (row.get("cameraSerial") or "").strip()
            model    = normalize_camera_model(row.get("cameraModel"))
            lat      = (row.get("latitude") or "").strip()
            lon      = (row.get("longitude") or "").strip()

            start_d  = parse_date(row.get("startLocal"))
            end_d    = parse_date(row.get("endLocal"))
            start_t  = parse_time(row.get("StartTime"))
            end_t    = parse_time(row.get(end_time_header)) if end_time_header else None

            offset   = normalize_offset(row.get("offset"), tz_hint_from_header, default_hint="EST")

            start_dt = combine_dt(start_d, start_t, end_of_day_if_none=False)
            end_dt   = combine_dt(end_d,   end_t,   end_of_day_if_none=True)

            start_iso = iso_with_offset(start_dt, offset)
            end_iso   = iso_with_offset(end_dt, offset)

            deploymentID = f"{siteID}_{serial}".strip("_")
            locationID   = (row.get("locationID") or siteID).strip()
            locationName = (row.get("locationName") or "").strip()
            setupBy      = (row.get("setUp") or "").strip()

            coord_unc    = safe_num(row.get("coordinateUncertainty"))
            cam_delay    = safe_num(row.get("cameraDelay"))
            cam_height   = safe_num(row.get("cameraHeight"))
            cam_depth    = safe_num(row.get("cameraDepth"))
            cam_tilt     = safe_num(row.get("cameraTilt"))
            cam_heading  = safe_num(row.get("cameraHeading"))
            detect_dist  = safe_num(row.get("detectionDistance"))
            ts_issues    = normalize_bool(row.get("timestampIssues"))
            bait_use     = normalize_bool(row.get("baitUse"))
            feature      = (row.get("featureType") or "").strip()
            habitat      = (row.get("habitat") or "").strip()
            groups       = (row.get("deploymentGroups") or "").strip()
            tags         = (row.get("deploymentTags") or "").strip()
            comments     = (row.get("comments") or "").strip()

            if i == 1:
                print("[INFO] Example first row →",
                      {"deploymentID": deploymentID, "start": start_iso, "end": end_iso, "cameraID": serial})

            w.writerow({
                "deploymentID": deploymentID,
                "locationID": locationID,
                "locationName": locationName,
                "latitude": lat,
                "longitude": lon,
                "coordinateUncertainty": coord_unc,
                "deploymentStart": start_iso,
                "deploymentEnd": end_iso,
                "setupBy": setupBy,
                "cameraID": serial,
                "cameraModel": model,
                "cameraDelay": cam_delay,
                "cameraHeight": cam_height,
                "cameraDepth": cam_depth,
                "cameraTilt": cam_tilt,
                "cameraHeading": cam_heading,
                "detectionDistance": detect_dist,
                "timestampIssues": ts_issues,
                "baitUse": bait_use,
                "featureType": feature,
                "habitat": habitat,
                "deploymentGroups": groups,
                "deploymentTags": tags,
                "deploymentComments": comments,
            })
            written += 1

    print(f" Wrote {OUT} ({written} rows)")

if __name__ == "__main__":
    main()
