# CamTrap DP data conversion

This project processes camera trap images and outputs standardized datasets in the Camtrap DP
 format.

It automates EXIF extraction, deployment metadata building, linking media to deployments, and generating observation templates for human annotation.

## Features
- Extract EXIF metadata from images using exiftool
Generate:
- deployments.csv → metadata about camera trap deployments (locations, devices, dates, people)
- media.csv → metadata about media files (images, timestamps, EXIF data, deployment links)
- observations.csv → placeholder observation records (later enriched with species info)

- Create a human labeling template (observations_to_label.csv) to enter species IDs, counts, etc.
- Merge human labels back into the observations table




## Inputs vs Outputs

**You provide (inputs):**

- Raw images under `data/` (subfolders OK)
- `datapackage/raw_deployment.csv` (your field sheet; see “Raw deployment columns” below)

**Scripts generate (outputs):**

After running the pipeline, you’ll have:
datapackage/
├─ deployments.csv # camera placements / sessions
├─ media.csv # media metadata (timestamp, path, MIME, EXIF, etc.)
├─ media_linked.csv # intermediate (media linked to deployments)
├─ observations.csv # one “media-level” row per image (unclassified baseline)
└─ media_metadata.json # raw EXIF per file (full or subset, depending on flags)

### Camtrap DP Tables

- **deployments.csv** → metadata about camera trap deployments (locations, dates, devices).
- **media.csv** → metadata about media files (images, timestamps, links to deployments).
- **observations.csv** → species observations (human).
- **datapackage.json** → dataset description and schema validation.

> Don’t hand-edit `media.csv` or `observations.csv` directly. Edit `observations_to_label.csv` and merge using `merge_labels.py`.

## Requirements

- Python 3.10+

- ExifTool (for full camera EXIF, including Reconyx serial numbers)

### Install ExifTool (one-time)

**Windows**

1. Download from https://exiftool.org/
2. Rename exiftool(-k).exe → exiftool.exe
3. EITHER add its folder to PATH or set an env var:

   - Option A: PATH (open a NEW terminal after this)
     setx PATH "$($env:PATH);C:\exiftool" _This is just an example PATH. Also, do not forget about the quotation marks around where your exif tool is located on your computer_

   - Option B:Set an environment variable (safer than editing PATH):

   ```powershell
   setx EXIFTOOL_PATH "C:\Tools\exiftool\exiftool.exe"

   ```

4. Test:
   Type out "exiftool -ver" in your terminal. Make sure you are in the correct folder # (works if in PATH)

**MacOS**

- brew install exiftool
  typically no env var needed (exiftool on PATH)

## Virtual Environment (recommended)

**Windows**
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

_If activation error:_
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1

**macOS / Linux**
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

If you want to stop your virtual environment then simply type "deactivate" in console.

To activate the virtual environment once made you can type ".venv\Scripts\Activate.ps1" 
Look at troubleshoot section if you are getting errors

### Run this when virtual environment is active:

- pip install -r requirements.txt


## Preflight Checklist
Before running run_all.py, make sure:
1. Images
- Place all camera trap photos inside data/
- Supported formats: .jpg, .jpeg, .png

2. Deployment Metadata
- Prepare your datapackage/raw_deployment.csv
- Must contain site info, camera serials, setup/retrieval times

3. ExifTool Installed
- Install exiftool (see Setup below)
Either:
- Add it to your PATH
- OR set EXIFTOOL_PATH environment variable

4. Python Environment
- Python 3.9+ recommended
- Install requirements: pip install -r requirements.txt

**If any of these are missing, the pipeline will fail early.**

## Run all the scripts at once:

Type "python scripts/run_all.py" in console
This will:

1. Extract EXIF → datapackage/media_linked.csv + datapackage/media_metadata.json

2. Build datapackage/deployments.csv (from your datapackage/raw_deployment.csv)

3. Link media ↔ deployments by camera SerialNumber → media_linked.csv

4. Copy media_linked.csv → media.csv

5. Build datapackage/observations.csv and a human label template → observations_to_label.csv

### You can also run the scripts one by one

1.  EXIF → media_linked.csv + media_metadata.json
    python scripts/extract_exif.py --data-dir data --recursive --embed-full-exif --file-public false
    If ExifTool isn’t auto-found, add:
    --exiftool "C:\Tools\exiftool\exiftool.exe"

2.  Build deployments.csv (reads datapackage/raw_deployment.csv)
    python scripts/build_deployments.py

3.  Link media to deployments via SerialNumber → media_linked.csv
    python scripts/link_media_by_serial.py

4.  Copy linked to final media.csv
    python -c "from shutil import copyfile; copyfile('datapackage/media_linked.csv','datapackage/media.csv')"

5.  Build observations + emit label template
    python scripts/build_observations.py --emit-label-template

## Labeling Animals

1. After you generate observations_to_label.csv with run_all.py or build_observations.py --emit-label-template, here’s what you actually do:

- Open datapackage/observations_to_label.csv in Excel, LibreOffice, or Google Sheets.

**Columns you can edit**

- observationType (animal|human|vehicle|blank|unknown|unclassified)
- scientificName (Latin)
- count (integer ≥ 1)
- lifeStage (adult|subadult|juvenile)
- sex (female|male)
- behavior (free text, |-separated, dominant first)
- observationComments
  Context columns (do not edit): observationID, mediaID, filePath, timestamp.

2. Annotate in Excel/Sheets:

- Fill only the fields you are confident about.
- Leave others blank to keep defaults.

3. Merge Back:

- When you’re done, just save the file as a CSV again (same filename, in the same datapackage/ folder).
- From the repo root, run:
  First, non-destructive merge
  python scripts/merge_labels.py

- Once you’ve checked observations_merged.csv looks correct then run:
  python scripts/merge_labels.py --inplace

## Raw Deployment Columns (input sheet)

Your datapackage/raw_deployment.csv should include at least:

- siteID (your location short code)

- cameraSerial (e.g., Reconyx SerialNumber)

- cameraModel

- latitude, longitude (decimal degrees; WGS84)

- startLocal, endLocal (deployment dates, local)

- StartTime, EndTime EST or a timezone offset (your script normalizes to ISO8601 with TZ)

- other metadata: locationID, locationName, setUp (who), coordinateUncertainty, cameraDelay, cameraHeight, cameraDepth, cameraTilt, cameraHeading, detectionDistance, timestampIssues, baitUse, featureType, habitat, deploymentGroups, deploymentTags, comments

## Troubleshooting

“exiftool is not recognized”

- Set env var (Windows):
  setx EXIFTOOL_PATH "C:\Tools\exiftool\exiftool.exe"

- Restart PowerShell:
  echo $env:EXIFTOOL_PATH
  or
  pass --exiftool "C:\Tools\exiftool\exiftool.exe" to extract_exif.py.

- python : The term 'python' is not recognized as the name of a cmdlet, function, script file, or operable program. Check the spelling of the name, or if a path was included, verify that the path is correct and try again.

1. Check if you have python installed.
Run: py --version or py -3 --version
If you see something like Python 3.11.5, Python is installed.

If not then please install python.

If python -m venv .venv does not work for virtual environment then try py -3 -m venv .venv, then activate it using .\.venv\Scripts\Activate.ps1

If .venv\Scripts\Activate.ps1 cannot be loaded 
because running scripts is disabled on this system. 

Then try to run "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass" and then try ".\.venv\Scripts\Activate.ps1"



