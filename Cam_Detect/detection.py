import cv2
import json
import time
from collections import deque
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
model = YOLO("yolov8n-pose.pt")

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
RUBBING = "RUBBING"
RINSING = "RINSING"
DRYING = "DRYING"
COMPLETE = "COMPLETE"

# ── Session variables ────────────────────────────────────────────
state = IDLE
session_start = 0.0
rub_start = 0.0
rub_duration = 0.0
dry_start = 0.0
dry_duration = 0.0
sink_entry_time = 0.0       # when person first entered sink without soap
steps_completed = []
last_seen = 0.0
result_display = ""
result_color = (255, 255, 255)
result_timer = 0.0
prev_lw = (0, 0)
prev_rw = (0, 0)
rub_confirm_count = 0

lw_history = deque(maxlen=3)
rw_history = deque(maxlen=3)

# ── Tuning ───────────────────────────────────────────────────────
MOTION_THRESHOLD = 3
RUBBING_CONFIRM_FRAMES = 8
NO_PERSON_TIMEOUT = 3.0
RESULT_DISPLAY_TIME = 4.0
WARNING_DURATION = 21.0
SESSION_TIMEOUT = 60.0
MIN_DRY_DURATION = 4.0
KEYPOINT_CONFIDENCE = 0.3
SOAP_GRACE_PERIOD = 4.0         # seconds to wait at sink before assuming no soap
ASSUMED_SOAP_DURATION = 10.0    # seconds of rubbing before assuming soap was used

# ── Helpers ──────────────────────────────────────────────────────
def point_in_zone(px, py, zone):
    return zone["x1"] < px < zone["x2"] and zone["y1"] < py < zone["y2"]

def wrist_in_zones(px, py, zone_type):
    return any(point_in_zone(px, py, z) for z in zones.get(zone_type, []))

def wrists_moving(lw, rw):
    lw_moved = abs(lw[0] - prev_lw[0]) + abs(lw[1] - prev_lw[1]) > MOTION_THRESHOLD
    rw_moved = abs(rw[0] - prev_rw[0]) + abs(rw[1] - prev_rw[1]) > MOTION_THRESHOLD
    return lw_moved or rw_moved

def smooth_wrist(history, new_point):
    history.append(new_point)
    avg_x = int(sum(p[0] for p in history) / len(history))
    avg_y = int(sum(p[1] for p in history) / len(history))
    return (avg_x, avg_y)

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
    has_rub = "rub" in steps_completed
    has_rinse = "rinse" in steps_completed
    has_dry = "dry" in steps_completed

    if has_soap and has_rub and has_rinse and has_dry and rub_duration >= min_wash_duration:
        result_display = "PASS"
        result_color = (0, 200, 0)
    elif has_rub and rub_duration >= WARNING_DURATION:
        result_display = "WARNING"
        result_color = (0, 165, 255)
    else:
        result_display = "FAIL"
        result_color = (0, 0, 255)

    print(f"\n{'='*30}")
    print(f"Result:          {result_display}")
    print(f"Steps completed: {steps_completed}")
    print(f"Rub duration:    {rub_duration:.1f}s")
    print(f"Dry duration:    {dry_duration:.1f}s")
    print(f"{'='*30}\n")

    state = COMPLETE
    result_timer = time.time()

def reset_session():
    global state, session_start, rub_start, rub_duration
    global dry_start, dry_duration, sink_entry_time
    global steps_completed, prev_lw, prev_rw
    global result_display, result_color, rub_confirm_count

    state = IDLE
    session_start = 0.0
    rub_start = 0.0
    rub_duration = 0.0
    dry_start = 0.0
    dry_duration = 0.0
    sink_entry_time = 0.0
    steps_completed = []
    prev_lw = (0, 0)
    prev_rw = (0, 0)
    rub_confirm_count = 0
    result_display = ""
    result_color = (255, 255, 255)
    lw_history.clear()
    rw_history.clear()

print("Running — press Q to quit\n")
frame_count = 0
last_keypoints = None

# ── Main loop ────────────────────────────────────────────────────
while True:
    ret, frame = cap.read()
    if not ret:
        break

    now = time.time()
    draw_zones(frame)

    if state not in (IDLE, COMPLETE) and (now - session_start) > SESSION_TIMEOUT:
        print("Session timed out")
        conclude_session()

    frame_count += 1
    if frame_count % 2 == 0:
        results = model(frame.copy(), verbose=False)
        last_keypoints = results[0].keypoints
    keypoints = last_keypoints

    person_detected = keypoints is not None and len(keypoints) > 0

    if person_detected:
        last_seen = now
        kp = keypoints.xy[0]
        kp_conf = results[0].keypoints.conf[0]

        lw_conf = float(kp_conf[LEFT_WRIST])
        rw_conf = float(kp_conf[RIGHT_WRIST])

        raw_lw = (int(kp[LEFT_WRIST][0]), int(kp[LEFT_WRIST][1])) if lw_conf > KEYPOINT_CONFIDENCE else prev_lw
        raw_rw = (int(kp[RIGHT_WRIST][0]), int(kp[RIGHT_WRIST][1])) if rw_conf > KEYPOINT_CONFIDENCE else prev_rw

        lw_px = smooth_wrist(lw_history, raw_lw)
        rw_px = smooth_wrist(rw_history, raw_rw)

        cv2.circle(frame, lw_px, 8, (0, 255, 255), -1)
        cv2.circle(frame, rw_px, 8, (0, 165, 255), -1)

        in_sink_lw = wrist_in_zones(lw_px[0], lw_px[1], "sink_tap")
        in_sink_rw = wrist_in_zones(rw_px[0], rw_px[1], "sink_tap")
        in_sink = in_sink_lw and in_sink_rw
        in_soap = (wrist_in_zones(lw_px[0], lw_px[1], "soap_dispenser") or
                   wrist_in_zones(rw_px[0], rw_px[1], "soap_dispenser"))
        in_dry = (wrist_in_zones(lw_px[0], lw_px[1], "dryer") or
                  wrist_in_zones(rw_px[0], rw_px[1], "dryer"))

        moving = wrists_moving(lw_px, rw_px)
        rubbing = in_sink and moving

        # ── State machine ────────────────────────────────────────
        if state == IDLE:
            if in_soap:
                # Person touched soap first — normal flow
                state = SOAPING
                session_start = now
                print("Session started — soap first")
            elif in_sink:
                # Person went straight to sink — start grace period
                # Don't commit to SOAPING or RUBBING yet
                state = SOAPING
                session_start = now
                sink_entry_time = now
                print("Session started — sink first, waiting for soap...")

        elif state == SOAPING:
            if in_soap:
                # Person reached soap zone — log it
                log_step("soap")
                sink_entry_time = 0.0  # clear grace period, soap confirmed

            # Allow rubbing only after soap is confirmed OR grace period has passed
            soap_confirmed = "soap" in steps_completed
            grace_passed = sink_entry_time > 0 and (now - sink_entry_time) > SOAP_GRACE_PERIOD

            if soap_confirmed or grace_passed:
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

                # If rubbing for 10s without soap step, assume soap was NOT used — mark as skipped
                if "soap" not in steps_completed and rub_duration >= ASSUMED_SOAP_DURATION:
                    print("  (soap skipped — rubbing 10s without soap step)")
            else:
                rub_confirm_count -= 1
                if rub_confirm_count <= 0:
                    if rub_duration >= WARNING_DURATION:
                        log_step("rub")
                        state = RINSING

            # Advance to rinsing when min duration met and hands leave sink
            if rub_duration >= min_wash_duration and not in_sink:
                log_step("rub")
                state = RINSING

        elif state == RINSING:
            log_step("rinse")
            if in_dry:
                state = DRYING
                dry_start = now

        elif state == DRYING:
            if in_dry:
                dry_duration += now - dry_start
                dry_start = now
            else:
                dry_start = now

            if dry_duration >= MIN_DRY_DURATION:
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

    if state == DRYING:
        cv2.putText(frame, f"Drying: {dry_duration:.1f}s / {MIN_DRY_DURATION}s",
                    (10, 83), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 1)

    if state == SOAPING and sink_entry_time > 0 and "soap" not in steps_completed:
        grace_remaining = max(0, SOAP_GRACE_PERIOD - (now - sink_entry_time))
        cv2.putText(frame, f"Waiting for soap... {grace_remaining:.1f}s",
                    (10, 83), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 1)

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