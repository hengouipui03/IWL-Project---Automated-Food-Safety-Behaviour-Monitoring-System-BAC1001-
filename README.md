# Automated Food Safety Behaviour Monitoring System

Monitors handwashing compliance from a camera using YOLO pose detection +
MediaPipe hand analysis, and reports results to a web dashboard that
implements all seven use cases from the requirements spec (UC-01 to UC-07)
with role-based access.

---

## What's in here

    dashboard_app.py     Web dashboard backend (Flask + SQLite)
    detection.py         Camera detection (YOLO + MediaPipe)
    integration.py       Sends detection results to the dashboard
    zone_setup.py        Tool to draw sink / soap / dryer zones
    hand_analysis.py     Hand-technique analysis
    pose_detectionV2.py  Pose helper
    site_config.json     Camera + zone configuration
    yolov8n-pose.pt      YOLO pose model
    templates/           Dashboard web pages (login + dashboard)
    setup.sh             One-command environment setup

Note: `compliance.db` is NOT in the repo — it is created automatically on
first run with demo accounts.

---

## Requirements

- A Mac, Windows, or Linux machine with a webcam
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) installed
- MediaPipe needs Python 3.11 (newer versions drop the API we use), so we
  create a dedicated Python 3.11 environment called `handwash`.

---

## Setup (one time)

Clone the repo, then from inside the folder:

**Mac / Linux:**

    bash setup.sh

**Windows (or manual on any OS):**

    conda create -n handwash python=3.11 -y
    conda activate handwash
    pip install flask requests ultralytics opencv-python mediapipe==0.10.14 numpy

---

## Draw the zones (one time per camera)

    conda activate handwash
    python zone_setup.py --config site_config.json

In the camera window:
- Press `1` then drag a box over the SINK / TAP
- Press `2` then drag a box over the SOAP dispenser
- Press `3` then drag a box over the DRYER / TOWEL
- `U` = undo last box, `S` = save & finish, `Q` = quit
- After `S`, type a site name and camera ID in the terminal.

To start zones from scratch, clear them first:

    python -c "import json; c=json.load(open('site_config.json')); c['zones']={'sink_tap':[],'soap_dispenser':[],'dryer':[]}; json.dump(c,open('site_config.json','w'),indent=2)"

---

## Run it (every time)

Two terminals.

Terminal 1 — dashboard:

    conda activate handwash
    python dashboard_app.py

Open http://localhost:5002

Terminal 2 — detection:

    conda activate handwash
    python detection.py --config site_config.json

Do a wash through the zones: soap -> rub (>=20s) -> rinse -> dry.
The result appears in the dashboard (switch views or refresh to update).

To stop either program, click its terminal and press Ctrl+C.

---

## Login accounts (demo)

All use password `password123`. The sidebar changes by role.

| User    | Role                        |
|---------|-----------------------------|
| manager | Site / Production Manager   |
| quality | Quality & Food Safety Team  |
| senior  | Senior / Regional Manager   |
| auditor | Auditor / Inspector (read-only) |
| admin   | System Administrator        |

Change these before any real use.

---

## Troubleshooting

**`Error: Could not open camera source 0`**
The camera index may differ. Edit `site_config.json` and change
`"camera_source"` to 1 (or run the camera-check snippet below).

    python -c "import cv2;[print(i,cv2.VideoCapture(i).isOpened()) for i in range(4)]"

**`module 'mediapipe' has no attribute 'solutions'`**
Wrong MediaPipe version. Fix:

    pip uninstall mediapipe -y && pip install mediapipe==0.10.14

**`TemplateNotFound: dashboard.html`**
Make sure `dashboard.html` and `login.html` are inside the `templates/`
folder.

**Port 5000/5002 in use**
On Mac, AirPlay can hold a port. The app uses 5002; if needed, change the
port in the last line of `dashboard_app.py`.

---

## Status / limitations

This is a working proof of concept. Not yet production-ready: it uses the
Flask dev server, demo passwords, and a hardcoded secret key, and the
GDPR data-retention auto-deletion and CCTV evidence linkage from the spec
are scaffolded but not automated.
