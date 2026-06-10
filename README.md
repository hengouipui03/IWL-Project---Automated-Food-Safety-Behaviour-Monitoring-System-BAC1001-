# Automated Food Safety Behaviour Monitoring System

Monitors handwashing compliance from a camera using YOLO pose detection +
MediaPipe hand analysis, and reports results to a web dashboard implementing
the seven use cases from the requirements spec (UC-01 to UC-07) with
role-based access.

All program code lives in the `detection_dashboard/` folder. It runs as two
separate programs from that folder:

    dashboard_app.py   the website (Flask web app + database)
    detection.py       the camera detection (YOLO + MediaPipe)

Detection sends each result to the dashboard over HTTP.

---

## Folder layout

    repo/
    ├── README.md
    ├── setup.sh
    └── detection_dashboard/
        ├── dashboard_app.py      web server + API + database logic
        ├── detection.py          main detection loop
        ├── hand_analysis.py      hand-technique analysis
        ├── pose_detectionV2.py   pose helper
        ├── zone_setup.py         tool to draw sink/soap/dryer zones
        ├── integration.py        sends results to the dashboard
        ├── site_config.json      camera + zone config (per machine)
        ├── yolov8n-pose.pt        YOLO pose model
        └── templates/
            ├── login.html
            └── dashboard.html

`compliance.db` is created automatically inside detection_dashboard/ on first
run and is not committed.

---

## Setup (one time)

From the repo root:

    bash setup.sh

Or manually:

    conda create -n handwash python=3.11 -y
    conda activate handwash
    pip install flask requests ultralytics opencv-python mediapipe==0.10.14 numpy

---

## Draw the zones (one time per camera)

    conda activate handwash
    cd detection_dashboard
    python zone_setup.py --config site_config.json

Keys: `1` sink/tap, `2` soap, `3` dryer (drag a box for each), `U` undo,
`S` save & finish, `Q` quit. After `S`, type a site name and camera ID.

---

## Run it (every time) - two terminals

Terminal 1 - dashboard (website):

    conda activate handwash
    cd detection_dashboard
    python dashboard_app.py

Open http://localhost:5002

Terminal 2 - detection (camera):

    conda activate handwash
    cd detection_dashboard
    python detection.py --config site_config.json

Do a wash through the zones: soap -> rub (>=20s) -> rinse -> dry.
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

- `module 'mediapipe' has no attribute 'solutions'` -> wrong env or version:
  `conda activate handwash` then `pip install mediapipe==0.10.14`
- `Could not open camera source 0` -> change `camera_source` in
  detection_dashboard/site_config.json (try 1), or grant camera permission.
- `TemplateNotFound` -> run the dashboard from inside detection_dashboard/.
- Port in use (Mac AirPlay uses 5000) -> app uses 5002; change in
  dashboard_app.py if needed.

## Status

Working proof of concept. Not yet production-hardened (Flask dev server,
demo passwords, no HTTPS; GDPR retention auto-deletion not automated).
