# Automated Food Safety Behaviour Monitoring System

Monitors handwashing compliance using a camera (YOLO pose detection) plus a
physical water sensor (via MQTT), and reports results to a web dashboard
implementing the seven use cases from the requirements spec (UC-01 to UC-07)
with role-based access.

The project has three parts, kept in separate folders:

    detection/   Camera + sensor side - watches the camera and the water
                 sensor together, grades handwashing, records evidence video
    dashboard/   Website side         - Flask web app + database, shown in
                 a browser
    sensors/     M5Stick device code  - runs ON the M5Stick itself (MicroPython,
                 not run on your laptop), publishes water readings over MQTT

Detection sends each result to the dashboard over HTTP. The water sensor
publishes its readings over MQTT; detection subscribes to those readings
directly and combines them with the camera to decide when rinsing has
actually happened.

---

## Folder layout

    repo/
    ├── README.md
    ├── setup.sh
    ├── detection/
    │   ├── detection.py            main detection loop (camera + MQTT sensor)
    │   ├── evidence_recorder.py    saves video evidence for FAIL/MISSED incidents
    │   │                           (and a 5% random sample of PASS incidents)
    │   ├── hand_analysis.py        hand-technique analysis (currently disabled)
    │   ├── pose_detectionV2.py     pose helper
    │   ├── zone_setup.py           tool to draw sink/soap/dryer zones
    │   ├── integration.py          sends results to the dashboard
    │   ├── site_config.json        camera + zone configuration (per machine)
    │   └── yolov8n-pose.pt          YOLO pose model
    ├── sensors/
    │   └── water_sensor.py         runs on the M5Stick (not your laptop) -
    │                                reads the SEN0114 sensor and publishes
    │                                to the MQTT broker over WiFi
    └── dashboard/
        ├── dashboard_app.py        web server + API + database logic
        ├── static/evidence/        saved incident video clips (created
        │                            automatically, gitignored)
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
    pip install flask requests ultralytics opencv-python mediapipe==0.10.14 numpy paho-mqtt imageio-ffmpeg

Note: detection currently runs even on base Python because the MediaPipe
technique analysis is disabled in the code. If it ever gets re-enabled, or you
hit "mediapipe has no attribute solutions", use the handwash env above.

`paho-mqtt` is required for detection to connect to the water sensor's MQTT
broker. If the broker isn't reachable (e.g. you're not on the same WiFi as
the sensor), detection prints a warning and continues running on camera data
alone - this is expected when testing away from the sensor.

`imageio-ffmpeg` is optional and only improves the format of saved evidence
videos; detection still runs without it.

---

## Draw the zones (one time per camera)

    conda activate handwash
    cd detection
    python zone_setup.py --config site_config.json

Keys: 1 = sink/tap, 2 = soap, 3 = dryer (drag a box for each), U = undo,
S = save & finish, Q = quit. After S, type a site name and camera ID.
Use SINK-001 / SINK-002 / SINK-003 as the camera ID so incidents map to a
seeded site (SINK-001/002 -> Central Kitchen, SINK-003 -> North Production Line).

Each person keeps their own site_config.json for their own camera - don't
overwrite someone else's zones with yours.

---

## Run it (every time) - two terminals

Terminal 1 - dashboard (website):

    cd dashboard
    python dashboard_app.py

Open http://localhost:5002

Terminal 2 - detection (camera + sensor):

    conda activate handwash
    cd detection
    python detection.py --config site_config.json

Do a wash through the zones: soap -> rub (>= the configured seconds) -> the
water sensor detects rinsing -> dry. Rinsing now advances based on the
physical water sensor (via MQTT), not a timer alone - if the sensor/broker
isn't reachable, detection will stay in the rubbing/rinsing state
indefinitely since it's waiting for a real water reading.

Start the dashboard first, then detection. Stop either with Ctrl+C.

The M5Stick (sensors/water_sensor.py) is programmed separately, onto the
M5Stick device itself via UIFlow/MicroPython - it does not run on your
laptop alongside the other two programs.

---

## Video evidence

FAIL and MISSED incidents automatically save a video clip to
dashboard/static/evidence/. PASS incidents keep a video only for a random
5% quality-control sample, to save storage. Video evidence has its own
retention setting under Rules & Alerts, as an admin.

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
- `No module named 'paho'` -> `pip install paho-mqtt`
- `Could not open camera source 0` -> change `camera_source` in
  detection/site_config.json (try 1), or grant camera permission.
- `MQTT could not connect...` -> expected if you're not on the same network
  as the sensor's broker; detection still runs, but rinsing won't advance
  without a real water reading.
- `TemplateNotFound` -> run the dashboard from inside the dashboard/ folder.
- `Port 5002 in use` -> `lsof -ti:5002 | xargs kill -9` (Mac), or change the
  port in the last line of dashboard_app.py.
- Manager / Quality only see their own site's data by design; use senior or
  admin to see all sites.

## Status

Working proof of concept. Not yet production-hardened (Flask dev server,
demo passwords, no HTTPS). Only handwashing is wired to live detection;
PPE and allergen are supported as categories but not yet detected.
GDPR retention is enforced for both incident records and video evidence
(each independently configurable, with purge).
