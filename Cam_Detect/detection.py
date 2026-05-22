import cv2
import json
import math
import time
from ultralytics import YOLO

# ── Load site config ─────────────────────────────────────────────
with open("site_config.json", "r") as f:
    config = json.load(f)

zones = config["zones"]
site_name = config["site_name"]
min_wash_duration = config["min_wash_duration"]

print(f"Site: {site_name}")
print(f"Min wash duration: {min_wash_duration}s")
print(f"Zones: { {k: len(v) for k, v in zones.items()} }")

# ── Zone colors ──────────────────────────────────────────────────
ZONE_COLORS = {
    "sink_tap": (0, 255, 0),
    "soap_dispenser": (255, 0, 0),
    "dryer": (255, 0, 255),
}

# ── YOLOv8 Pose ──────────────────────────────────────────────────
model = YOLO("yolov8m-pose.pt")

LEFT_WRIST = 9
RIGHT_WRIST = 10

# ── Webcam ───────────────────────────────────────────────────────
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("Error: Could not open webcam")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# ── Window setup ─────────────────────────────────────────────────
cv2.namedWindow("Handwash Detection", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Handwash Detection", 1280, 960)

# ── Session states ───────────────────────────────────────────────
IDLE = "IDLE"
SOAPING = "SOAPING"
WETTING = "WETTING"
RUBBING = "RUBBING"
RINSING = "RINSING"
DRYING = "DRYING"
COMPLETE = "COMPLETE"

# ── Session variables ────────────────────────────────────────────
state = IDLE
session_start = 0.0
rub_start = 0.0
rub_duration = 0.0
sink_visit_count = 0
steps_completed = []
last_seen = 0.0
result_display = ""
result_color = (255, 255, 255)
result_timer = 0.0
prev_lw = (0, 0)
prev_rw = (0, 0)
rub_confirm_count = 0

# ── Tuning ───────────────────────────────────────────────────────
MOTION_THRESHOLD = 8
RUBBING_CONFIRM_FRAMES = 8
NO_PERSON_TIMEOUT = 3.0
RESULT_DISPLAY_TIME = 4.0
WARNING_DURATION = 10.0

# ── Helpers ──────────────────────────────────────────────────────
def point_in_zone(px, py, zone):
    return zone["x1"] < px < zone["x2"] and zone["y1"] < py < zone["y2"]

def wrist_in_zones(px, py, zone_type):
    return any(point_in_zone(px, py, z) for z in zones.get(zone_type, []))

def wrists_moving(lw, rw):
    lw_moved = abs(lw[0] - prev_lw[0]) + abs(lw[1] - prev_lw[1]) > MOTION_THRESHOLD
    rw_moved = abs(rw[0] - prev_rw[0]) + abs(rw[1] - prev_rw[1]) > MOTION_THRESHOLD
    return lw_moved or rw_moved

def draw_zones(frame):
    for zone_type, zone_list in zones.items():
        color = ZONE_COLORS.get(zone_type, (255, 255, 255))
        for i, z in enumerate(zone_list):
            cv2.rectangle(frame, (z["x1"], z["y1"]), (z["x2"], z["y2"]), color, 2)
            cv2.putText(frame, f"{zone_type} #{i+1}",
                        (z["x1"] + 4, z["y1"] + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

def log_step(step):
    if step not in steps_completed:
        steps_completed.append(step)
        print(f"  ✔ Step: {step}")

def conclude_session():
    global state, result_display, result_color, result_timer

    has_soap = "soap" in steps_completed
    has_wet = "wet" in steps_completed
    has_rub = "rub" in steps_completed
    has_rinse = "rinse" in steps_completed
    has_dry = "dry" in steps_completed

    if has_soap and has_wet and has_rub and has_rinse and has_dry and rub_duration >= min_wash_duration:
        result_display = "PASS"
        result_color = (0, 200, 0)
    elif has_wet and has_rub and rub_duration >= WARNING_DURATION:
        result_display = "WARNING"
        result_color = (0, 165, 255)
    else:
        result_display = "FAIL"
        result_color = (0, 0, 255)

    print(f"\n{'='*30}")
    print(f"Result:          {result_display}")
    print(f"Steps completed: {steps_completed}")
    print(f"Rub duration:    {rub_duration:.1f}s")
    print(f"{'='*30}\n")

    state = COMPLETE
    result_timer = time.time()

def reset_session():
    global state, session_start, rub_start, rub_duration
    global sink_visit_count, steps_completed, prev_lw, prev_rw
    global result_display, result_color, rub_confirm_count

    state = IDLE
    session_start = 0.0
    rub_start = 0.0
    rub_duration = 0.0
    sink_visit_count = 0
    steps_completed = []
    prev_lw = (0, 0)
    prev_rw = (0, 0)
    rub_confirm_count = 0
    result_display = ""
    result_color = (255, 255, 255)

print("Running — press Q to quit\n")

# ── Main loop ────────────────────────────────────────────────────
while True:
    ret, frame = cap.read()
    if not ret:
        break

    now = time.time()
    draw_zones(frame)

    # Run YOLOv8 on a copy so it cannot draw on our frame
    results = model(frame.copy(), verbose=False)
    keypoints = results[0].keypoints

    person_detected = keypoints is not None and len(keypoints) > 0

    if person_detected:
        last_seen = now
        kp = keypoints.xy[0]

        lw_px = (int(kp[LEFT_WRIST][0]), int(kp[LEFT_WRIST][1]))
        rw_px = (int(kp[RIGHT_WRIST][0]), int(kp[RIGHT_WRIST][1]))

        # Draw wrist dots only
        cv2.circle(frame, lw_px, 8, (0, 255, 255), -1)  # yellow = left wrist
        cv2.circle(frame, rw_px, 8, (0, 165, 255), -1)  # orange = right wrist

        # Zone checks
        in_sink_lw = wrist_in_zones(lw_px[0], lw_px[1], "sink_tap")
        in_sink_rw = wrist_in_zones(rw_px[0], rw_px[1], "sink_tap")
        in_sink = in_sink_lw and in_sink_rw
        in_soap = (wrist_in_zones(lw_px[0], lw_px[1], "soap_dispenser") or
                   wrist_in_zones(rw_px[0], rw_px[1], "soap_dispenser"))
        in_dry = (wrist_in_zones(lw_px[0], lw_px[1], "dryer") or
                  wrist_in_zones(rw_px[0], rw_px[1], "dryer"))

        # Rubbing only counts when both wrists are inside the sink zone and moving
        moving = wrists_moving(lw_px, rw_px)
        rubbing = in_sink and moving

        # ── State machine ────────────────────────────────────────
        if state == IDLE:
            if in_soap or in_sink:
                state = SOAPING if in_soap else WETTING
                session_start = now
                sink_visit_count = 1 if in_sink else 0
                print(f"Session started — first contact: {'soap' if in_soap else 'sink'}")

        elif state == SOAPING:
            log_step("soap")
            if in_sink:
                state = WETTING
                sink_visit_count += 1

        elif state == WETTING:
            log_step("wet")
            if rubbing:
                rub_confirm_count += 1
                if rub_confirm_count >= RUBBING_CONFIRM_FRAMES:
                    state = RUBBING
                    rub_start = now
            else:
                rub_confirm_count = 0

        elif state == RUBBING:
            if rubbing:
                rub_duration += now - rub_start
                rub_start = now
                rub_confirm_count = RUBBING_CONFIRM_FRAMES
            else:
                rub_confirm_count -= 1
                if rub_confirm_count <= 0:
                    log_step("rub")
                    if rub_duration >= WARNING_DURATION:
                        state = RINSING
                    else:
                        rub_start = now

            if rub_duration >= min_wash_duration and not in_sink:
                log_step("rub")
                state = RINSING

        elif state == RINSING:
            log_step("rinse")
            if in_dry:
                state = DRYING

        elif state == DRYING:
            log_step("dry")
            conclude_session()

        elif state == COMPLETE:
            if now - result_timer > RESULT_DISPLAY_TIME:
                reset_session()

        prev_lw = lw_px
        prev_rw = rw_px

    else:
        if state not in (IDLE, COMPLETE):
            if now - last_seen > NO_PERSON_TIMEOUT:
                print("Person left early — ending session")
                if steps_completed:
                    conclude_session()
                else:
                    result_display = "MISSED"
                    result_color = (0, 165, 255)
                    result_timer = now
                    state = COMPLETE
                    print("MISSED — no steps completed")

    # ── HUD ──────────────────────────────────────────────────────
    elapsed = (now - session_start) if state not in (IDLE, COMPLETE) else 0.0

    cv2.putText(frame, f"State: {state}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 255, 0) if person_detected else (0, 0, 255), 2)
    cv2.putText(frame, f"Session: {elapsed:.1f}s", (10, 58),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

    if state == RUBBING:
        cv2.putText(frame, f"Rubbing: {rub_duration:.1f}s / {min_wash_duration}s",
                    (10, 83), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)

    steps_str = " → ".join(steps_completed) if steps_completed else "none"
    cv2.putText(frame, f"Steps: {steps_str}", (10, 108),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    if result_display and state == COMPLETE:
        cv2.putText(frame, result_display, (150, 280),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, result_color, 4)

    cv2.putText(frame, site_name, (10, 470),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)

    cv2.imshow("Handwash Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ── Cleanup ──────────────────────────────────────────────────────
cap.release()
cv2.destroyAllWindows()