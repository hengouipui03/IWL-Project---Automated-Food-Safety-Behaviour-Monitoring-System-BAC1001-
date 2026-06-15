# Automated Food Safety Behaviour Monitoring System

Monitors handwashing compliance from a camera using YOLO pose detection +
MediaPipe hand analysis, and reports results to a web dashboard implementing
the seven use cases from the requirements spec (UC-01 to UC-07) with
role-based access.

The project has two halves, kept in separate folders:

    detection/   Camera side  - watches the camera, grades handwashing
    dashboard/   Website side - Flask web app + database, shown in a browser

They run as two separate programs. Detection sends each result to the
dashboard over HTTP.

---

## Folder layout

    repo/
    ├── README.md
    ├── setup.sh
    ├── detection/
    │   ├── detection.py          main detection loop
    │   ├── hand_analysis.py      hand-technique analysis (currently disabled in detection)
    │   ├── pose_detectionV2.py   pose helper
    │   ├── zone_setup.py         tool to draw sink/soap/dryer zones
    │   ├── integration.py        sends results to the dashboard
    │   ├── site_config.json      camera + zone configuration (per machine)
    │   └── yolov8n-pose.pt        YOLO pose model
    └── dashboard/
        ├── dashboard_app.py      web server + API + database logic
        └── templates/
            ├── login.html
            └── dashboard.html

`compliance.db` is created automatically inside dashboard/ on first run.
To reset to a clean slate, stop the dashboard and delete dashboard/compliance.db.

---

## Setup (one time)

From the repo root:

    bash setup.sh

Or manually:

    conda create -n handwash python=3.11 -y
    conda activate handwash
    pip install flask requests ultralytics opencv-python mediapipe==0.10.14 numpy

Note: detection currently runs even on base Python because the MediaPipe
technique analysis is disabled in the code. If it ever gets re-enabled, or you
hit "mediapipe has no attribute solutions", use the handwash env above.

---

## Draw the zones (one time per camera)

    conda activate handwash
    cd detection
    python zone_setup.py --config site_config.json

Keys: 1 = sink/tap, 2 = soap, 3 = dryer (drag a box for each), U = undo,
S = save & finish, Q = quit. After S, type a site name and camera ID.
Use SINK-001 / SINK-002 / SINK-003 as the camera ID so incidents map to a
seeded site (SINK-001/002 -> Central Kitchen, SINK-003 -> North Production Line).

---

## Run it (every time) - two terminals

Terminal 1 - dashboard (website):

    cd dashboard
    python dashboard_app.py

Open http://localhost:5002

Terminal 2 - detection (camera):

    conda activate handwash
    cd detection
    python detection.py --config site_config.json

Do a wash through the zones: soap -> rub (>= the configured seconds) -> rinse -> dry.
Start the dashboard first, then detection. Stop either with Ctrl+C.

---

## Login accounts (demo - change before real use)

All use password `password123`:

| User    | Role                            |
|---------|---------------------------------|
| manager | Site / Production Manager       |
| quality | Quality & Food Safety Team      |
| senior  | Senior / Regional Manager       |
| auditor | Auditor / Inspector (read-only) |
| admin   | System Administrator            |

---

## Troubleshooting

- `module 'mediapipe' has no attribute 'solutions'` -> use the handwash env:
  `conda activate handwash` then `pip install mediapipe==0.10.14`
- `Could not open camera source 0` -> change `camera_source` in
  detection/site_config.json (try 1), or grant camera permission.
- `TemplateNotFound` -> run the dashboard from inside the dashboard/ folder.
- `Port 5002 in use` -> `lsof -ti:5002 | xargs kill -9` (Mac), or change the
  port in the last line of dashboard_app.py.
- Manager / Quality only see their own site's data by design; use senior or
  admin to see all sites.

## Status

Working proof of concept. Not yet production-hardened (Flask dev server,
demo passwords, no HTTPS). Only handwashing is wired to live detection;
PPE and allergen are supported as categories but not yet detected.
GDPR retention is enforced (configurable, with purge).
