# Automated Food Safety Behaviour Monitoring System

Monitors handwashing compliance using a camera (YOLO pose detection) combined
with physical IoT sensors (a water/flow sensor and a soap-dispenser button,
read over MQTT), and reports results to a web dashboard implementing the seven
use cases from the requirements spec (UC-01 to UC-07) with role-based access.

The project has three parts, kept in separate folders:

    detection/   Camera + sensor side - watches the camera and listens to the
                 IoT sensors (via MQTT) together, grades handwashing, and
                 records video evidence
    dashboard/   Website side         - Flask web app + database, shown in a
                 browser
    sensors/     M5Stack device code  - runs ON the M5Stack devices themselves
                 (MicroPython via UIFlow), NOT on your laptop; each publishes
                 its sensor reading to the MQTT broker over WiFi

Detection sends each result to the dashboard over HTTP. The M5Stack sensors
publish their readings over MQTT; detection subscribes to those topics and
combines them with the camera - for example, rinsing only counts as done when
the water sensor actually reports water flow.

---

## Folder layout

    repo/
    |-- README.md
    |-- setup.sh
    |-- detection/
    |   |-- detection.py            main loop (camera + MQTT sensors)
    |   |-- evidence_recorder.py    saves video evidence for incidents
    |   |-- hand_analysis.py        hand-technique analysis (currently disabled)
    |   |-- pose_detectionV2.py     pose helper
    |   |-- zone_setup.py           tool to draw sink/soap/dryer zones
    |   |-- integration.py          sends results to the dashboard over HTTP
    |   |-- site_config.json        camera, zones AND MQTT settings (per machine)
    |   \-- yolov8n-pose.pt         YOLO pose model
    |-- sensors/
    |   |-- water_sensor.py         runs on an M5Stack - water/flow sensor,
    |   |                            publishes to the MQTT broker
    |   \-- touch_sensor.py         runs on an M5Stack - soap-dispenser button,
    |                                publishes to the MQTT broker
    \-- dashboard/
        |-- dashboard_app.py        web server + API + database logic
        |-- static/evidence/        saved incident video clips (created at runtime)
        \-- templates/
            |-- login.html
            \-- dashboard.html

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

Package notes:
- `paho-mqtt` is required - detection connects to the sensors' MQTT broker.
  If the broker isn't reachable (e.g. you're not on the same network as the
  sensors), detection prints a warning and keeps running on camera data alone.
- `imageio-ffmpeg` is optional and only improves the saved evidence-video
  format; detection still runs without it.
- detection currently runs even on base Python because the MediaPipe technique
  analysis is disabled in the code. If it's ever re-enabled, or you hit
  "mediapipe has no attribute solutions", use the handwash env above.

The M5Stack sensor code (sensors/water_sensor.py, sensors/touch_sensor.py) is
NOT installed with pip and does NOT run on your computer. It is copied into the
M5Stack UIFlow IDE and flashed onto the M5Stack devices themselves. Set the
WiFi and MQTT broker details at the top of those files to match your network.

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

## Configure the sensors (site_config.json)

The MQTT connection is read from site_config.json. Add these keys (values must
match what the M5Stack devices publish to):

    "mqtt_broker": "192.168.137.1",
    "mqtt_port": 1883,
    "mqtt_topic_flow": "water/sensor1",
    "mqtt_topic_button": "sensors/button"

If these keys are omitted, detection defaults to localhost:1883 with the topics
above. On the M5Stack side, set WIFI_SSID / WIFI_PASSWORD / MQTT_BROKER at the
top of water_sensor.py and touch_sensor.py to the same network and broker.

Sensor message format (what the M5Stacks publish):
- Flow topic:   ">2000" = water detected, "<2000" = no water
- Button topic: "1" = pressed (simulates soap dispensed)

---

## Run it (every time) - two terminals

Terminal 1 - dashboard (website):

    cd dashboard
    python dashboard_app.py

Open http://localhost:5002

Terminal 2 - detection (camera + sensors):

    conda activate handwash
    cd detection
    python detection.py --config site_config.json

Do a wash through the zones: soap -> rub (>= the configured seconds) -> the
water sensor detects rinsing -> dry. Rinsing advances on the real water sensor
reading (via MQTT), not a timer - so if the broker isn't reachable, detection
waits at that stage for a real water reading.

Start the dashboard first, then detection. Stop either with Ctrl+C.
The M5Stack sensors run independently on their own hardware.

---

## Video evidence

FAIL and MISSED incidents automatically save a video clip to
dashboard/static/evidence/. PASS incidents keep a video only for a random 5%
quality-control sample, to save storage. Video evidence has its own retention
setting - separate from the incident record and capped at or below it - under
Rules & Alerts (admin only). It can be set as low as 0 days for same-day removal.

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
- `MQTT could not connect...` -> expected if you're not on the same network as
  the sensors' broker; detection keeps running, but rinsing won't advance
  without a real water reading.
- `TemplateNotFound` -> run the dashboard from inside the dashboard/ folder.
- `Port 5002 in use` -> `lsof -ti:5002 | xargs kill -9` (Mac), or change the
  port in the last line of dashboard_app.py.
- Manager / Quality only see their own site's data by design; use senior or
  admin to see all sites.

## Status

Working proof of concept. Not yet production-hardened (Flask dev server, demo
passwords, no HTTPS). Only handwashing is wired to live detection; PPE and
allergen are supported as categories but not yet detected. GDPR retention is
enforced for both incident records and video evidence (each independently
configurable, with purge). Purge runs on dashboard startup and on demand
("Purge now") - not on a continuous schedule.
