import cv2
import argparse
import json
import time
import platform
import threading
import numpy as np
from collections import deque
from ultralytics import YOLO
from hand_analysis import HandAnalyser
from integration import send_to_dashboard

# ── Load site config ─────────────────────────────────────────────
def parse_camera_source(source):
    if isinstance(source, str) and source.isdigit():
        return int(source)
    return source

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="site_config.json")
args = parser.parse_args()

config_path = args.config

with open(config_path, "r") as f:
    config = json.load(f)

zones = config["zones"]
site_name = config["site_name"]
min_wash_duration = config["min_wash_duration"]
camera_id = config.get("camera_id", site_name)
camera_source = parse_camera_source(config.get("camera_source", 0))
frame_width = config.get("frame_width", 480)
frame_height = config.get("frame_height", 480)

print(f"Config: {config_path}")
print(f"Camera ID: {camera_id}")
print(f"Camera source: {camera_source}")
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

LEFT_WRIST     = 9
RIGHT_WRIST    = 10
LEFT_SHOULDER  = 5
RIGHT_SHOULDER = 6
LEFT_HIP       = 11
RIGHT_HIP      = 12
LEFT_KNEE      = 13
RIGHT_KNEE     = 14

# ── MediaPipe Hand Analyser ───────────────────────────────────────
analyser = HandAnalyser()

# ── Webcam ───────────────────────────────────────────────────────
if isinstance(camera_source, int):
    if platform.system() == "Windows":
        cap = cv2.VideoCapture(camera_source, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(camera_source)
else:
    cap = cv2.VideoCapture(camera_source)

if not cap.isOpened():
    print(f"Error: Could not open camera source {camera_source}")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)

# ── Window setup ─────────────────────────────────────────────────
cv2.namedWindow("Handwash Detection", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Handwash Detection", 1280, 960)

# ── Session states ───────────────────────────────────────────────
IDLE            = "IDLE"
SOAPING         = "SOAPING"
RUBBING         = "RUBBING"
RINSING         = "RINSING"
DRYING          = "DRYING"
RECONTAMINATION = "RECONTAMINATION"
COMPLETE        = "COMPLETE"

# ── Session variables ────────────────────────────────────────────
state                         = IDLE
session_start                 = 0.0
rub_start                     = 0.0
rub_duration                  = 0.0
last_rub_time                 = 0.0
dry_start                     = 0.0
dry_duration                  = 0.0
sink_entry_time               = 0.0
recontamination_contact_start = 0.0
steps_completed               = []
last_seen                     = 0.0
result_display                = ""
result_color                  = (255, 255, 255)
result_timer                  = 0.0
prev_lw                       = (0, 0)
prev_rw                       = (0, 0)
rub_confirm_count             = 0
technique_summary             = None
soap_entry_time               = 0.0
body_dry_start                = 0.0
body_dry_duration             = 0.0
body_dry_wrist_history        = deque(maxlen=45)  # ~1.5s at 30fps

lw_history = deque(maxlen=3)
rw_history = deque(maxlen=3)

# ── Tuning ───────────────────────────────────────────────────────
MOTION_THRESHOLD          = 3
RUBBING_CONFIRM_FRAMES    = 8
NO_PERSON_TIMEOUT         = 3.0
RESULT_DISPLAY_TIME       = 4.0
SESSION_TIMEOUT           = 60.0
MIN_DRY_DURATION          = 5.0
KEYPOINT_CONFIDENCE       = 0.3
SOAP_GRACE_PERIOD         = 4.0
ASSUMED_SOAP_DURATION     = 10.0
RUB_PAUSE_TOLERANCE       = 2.0
SOAP_DWELL_TIME           = 0.8
BODY_DRY_MIN_DURATION     = 1.5
BODY_DRY_MIN_DISPLACEMENT = 8
BODY_DRY_MIN_REVERSALS    = 3
RECONTAMINATION_MONITOR_TIME  = 8.0
RECONTAMINATION_CONFIRM_TIME  = 0.8
RECONTAMINATION_LEAVE_TIMEOUT = 1.0

# ── Frame skip for performance ───────────────────────────────────
frame_count    = 0
last_keypoints = None

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

def get_body_zone(kp, kp_conf):
    """Single chest-width box from shoulders down to hip midpoint."""
    def get_kp(idx):
        if float(kp_conf[idx]) > KEYPOINT_CONFIDENCE:
            return (int(kp[idx][0]), int(kp[idx][1]))
        return None

    ls = get_kp(LEFT_SHOULDER)
    rs = get_kp(RIGHT_SHOULDER)
    lh = get_kp(LEFT_HIP)
    rh = get_kp(RIGHT_HIP)

    if not ls or not rs:
        return None

    shoulder_w = abs(ls[0] - rs[0])
    x1 = min(ls[0], rs[0]) + int(shoulder_w * 0.1)
    x2 = max(ls[0], rs[0]) - int(shoulder_w * 0.1)
    if x1 >= x2:
        x1 = min(ls[0], rs[0])
        x2 = max(ls[0], rs[0])
    y1 = min(ls[1], rs[1])

    if lh and rh:
        y2 = int((lh[1] + rh[1]) / 2) + 10
    else:
        y2 = int(max(ls[1], rs[1]) + shoulder_w * 0.65)

    return (x1, y1, x2, y2)

def wrist_in_body_zone(px, py, box):
    if box is None:
        return False
    x1, y1, x2, y2 = box
    return x1 < px < x2 and y1 < py < y2

def draw_body_zone(frame, box):
    if box is None:
        return
    x1, y1, x2, y2 = box
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 100, 255), -1)
    cv2.addWeighted(overlay, 0.10, frame, 0.90, 0, frame)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 120, 255), 2)
    cv2.putText(frame, "body zone", (x1 + 4, y1 + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 140, 255), 1)

def draw_skeleton(frame, kp, kp_conf):
    """Draw full skeleton every frame to stabilise keypoint confidence."""
    SKELETON_EDGES = [
        (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
        (5, 11), (6, 12), (11, 12),
        (11, 13), (13, 15), (12, 14), (14, 16),
        (0, 1), (0, 2), (1, 3), (2, 4),
    ]
    pts = {}
    for i in range(len(kp_conf)):
        if float(kp_conf[i]) > KEYPOINT_CONFIDENCE:
            pts[i] = (int(kp[i][0]), int(kp[i][1]))
            cv2.circle(frame, pts[i], 4, (180, 180, 180), -1)
    for a, b in SKELETON_EDGES:
        if a in pts and b in pts:
            cv2.line(frame, pts[a], pts[b], (100, 100, 100), 1)

def detect_oscillation(history):
    """Count X+Y direction reversals — works for front-facing and top-down cameras."""
    if len(history) < 4:
        return False
    positions = list(history)
    reversals = 0
    prev_dx   = 0
    prev_dy   = 0
    for i in range(1, len(positions)):
        px, py, _ = positions[i - 1]
        cx, cy, _ = positions[i]
        dx = cx - px
        dy = cy - py
        if abs(dx) >= BODY_DRY_MIN_DISPLACEMENT:
            if prev_dx != 0 and ((dx > 0) != (prev_dx > 0)):
                reversals += 1
            prev_dx = dx
        if abs(dy) >= BODY_DRY_MIN_DISPLACEMENT:
            if prev_dy != 0 and ((dy > 0) != (prev_dy > 0)):
                reversals += 1
            prev_dy = dy
    return reversals >= BODY_DRY_MIN_REVERSALS

def log_step(step):
    if step not in steps_completed:
        steps_completed.append(step)
        print(f"  ✔ Step: {step}")

def conclude_session():
    global state, result_display, result_color, result_timer, technique_summary

    has_soap  = "soap"  in steps_completed
    has_rub   = "rub"   in steps_completed
    has_rinse = "rinse" in steps_completed
    has_dry   = "dry"   in steps_completed

    technique_summary = analyser.get_summary()

    if has_soap and has_rub and has_rinse and has_dry and rub_duration >= min_wash_duration:
        result_display = "PASS"
        result_color   = (0, 200, 0)
    else:
        result_display = "FAIL"
        result_color   = (0, 0, 255)

    expected = ["soap", "rub", "rinse", "dry"]
    missed   = [s for s in expected if s not in steps_completed]

    print(f"\n{'='*30}")
    print(f"Result:          {result_display}")
    print(f"Steps completed: {steps_completed}")
    print(f"Missed steps:    {missed}")
    print(f"Rub duration:    {rub_duration:.1f}s")
    print(f"Dry duration:    {dry_duration:.1f}s")
    if "recontamination" in steps_completed:
        print("  ⚠ Recontamination flagged")
    if "body_drying" in steps_completed:
        print("  ⚠ Body drying flagged — hands dried on body instead of dryer")
    print(f"\n── Technique Summary ──")
    print(f"Score:           {technique_summary['technique_score']}/4")
    print(f"Palm up:         {technique_summary['palm_up']}")
    print(f"Palm down:       {technique_summary['palm_down']}")
    print(f"Fingers spread:  {technique_summary['fingers_spread']}")
    print(f"Wrist rubbed:    {technique_summary['wrist_rubbed']}")
    if technique_summary['missing']:
        print(f"Missing:         {technique_summary['missing']}")
    print(f"{'='*30}\n")

    state        = COMPLETE
    result_timer = time.time()
    # Non-blocking — runs in background so the main loop never freezes
    threading.Thread(
        target=send_to_dashboard,
        args=(result_display, steps_completed, rub_duration, camera_id),
        daemon=True
    ).start()

def reset_session():
    global state, session_start, rub_start, rub_duration, last_rub_time
    global dry_start, dry_duration, sink_entry_time, recontamination_contact_start
    global steps_completed, prev_lw, prev_rw
    global result_display, result_color, rub_confirm_count, technique_summary
    global soap_entry_time, body_dry_start, body_dry_duration

    state                         = IDLE
    session_start                 = 0.0
    rub_start                     = 0.0
    rub_duration                  = 0.0
    last_rub_time                 = 0.0
    dry_start                     = 0.0
    dry_duration                  = 0.0
    sink_entry_time               = 0.0
    recontamination_contact_start = 0.0
    steps_completed               = []
    prev_lw                       = (0, 0)
    prev_rw                       = (0, 0)
    rub_confirm_count             = 0
    result_display                = ""
    result_color                  = (255, 255, 255)
    technique_summary             = None
    soap_entry_time               = 0.0
    body_dry_start                = 0.0
    body_dry_duration             = 0.0
    body_dry_wrist_history.clear()
    lw_history.clear()
    rw_history.clear()
    analyser.reset()

print("Running — press Q to quit\n")

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

    # Run YOLO every other frame for performance
    frame_count += 1
    if frame_count % 2 == 0:
        results        = model(frame.copy(), verbose=False)
        last_keypoints = results[0].keypoints
    keypoints = last_keypoints

    person_detected = keypoints is not None and len(keypoints) > 0

    if person_detected:
        kp      = keypoints.xy[0]
        kp_conf = keypoints.conf[0]

        lw_conf    = float(kp_conf[LEFT_WRIST])
        rw_conf    = float(kp_conf[RIGHT_WRIST])
        lw_visible = lw_conf > KEYPOINT_CONFIDENCE
        rw_visible = rw_conf > KEYPOINT_CONFIDENCE

        raw_lw = (int(kp[LEFT_WRIST][0]),  int(kp[LEFT_WRIST][1]))  if lw_visible else None
        raw_rw = (int(kp[RIGHT_WRIST][0]), int(kp[RIGHT_WRIST][1])) if rw_visible else None

        if raw_lw is not None:
            lw_px = smooth_wrist(lw_history, raw_lw)
            cv2.circle(frame, lw_px, 8, (0, 255, 255), -1)
        else:
            lw_px = None
            lw_history.clear()

        if raw_rw is not None:
            rw_px = smooth_wrist(rw_history, raw_rw)
            cv2.circle(frame, rw_px, 8, (0, 165, 255), -1)
        else:
            rw_px = None
            rw_history.clear()

        # Draw full skeleton every frame — stabilises keypoint confidence
        draw_skeleton(frame, kp, kp_conf)

        valid_wrist_detected = lw_px is not None or rw_px is not None
        if valid_wrist_detected:
            last_seen = now

        in_sink_lw = lw_px is not None and wrist_in_zones(lw_px[0], lw_px[1], "sink_tap")
        in_sink_rw = rw_px is not None and wrist_in_zones(rw_px[0], rw_px[1], "sink_tap")
        in_sink    = in_sink_lw and in_sink_rw
        in_soap    = ((lw_px is not None and wrist_in_zones(lw_px[0], lw_px[1], "soap_dispenser")) or
                      (rw_px is not None and wrist_in_zones(rw_px[0], rw_px[1], "soap_dispenser")))
        in_dry_lw  = lw_px is not None and wrist_in_zones(lw_px[0], lw_px[1], "dryer")
        in_dry_rw  = rw_px is not None and wrist_in_zones(rw_px[0], rw_px[1], "dryer")
        in_dry     = in_dry_lw and in_dry_rw  # both wrists required

        moving  = wrists_moving(lw_px, rw_px) if lw_px is not None and rw_px is not None else False
        rubbing = in_sink and moving

        # ── State machine ────────────────────────────────────────
        if state == IDLE:
            if in_soap:
                state         = SOAPING
                session_start = now
                analyser.reset()
                print("Session started — soap first")
            elif in_sink:
                state           = SOAPING
                session_start   = now
                sink_entry_time = now
                analyser.reset()
                print("Session started — sink first, waiting for soap...")

        elif state == SOAPING:
            if in_soap and "soap" not in steps_completed:
                if soap_entry_time == 0.0:
                    soap_entry_time = now
                    print("Soap zone entered — waiting for dwell confirmation...")
                elif now - soap_entry_time >= SOAP_DWELL_TIME:
                    log_step("soap")
                    sink_entry_time = 0.0
            elif not in_soap:
                if soap_entry_time > 0 and "soap" not in steps_completed:
                    soap_entry_time = 0.0

            soap_confirmed = "soap" in steps_completed
            grace_passed   = sink_entry_time > 0 and (now - sink_entry_time) > SOAP_GRACE_PERIOD

            if soap_confirmed or grace_passed:
                if rubbing:
                    rub_confirm_count += 1
                    if rub_confirm_count >= RUBBING_CONFIRM_FRAMES:
                        state         = RUBBING
                        rub_start     = now
                        last_rub_time = now
                else:
                    rub_confirm_count = 0

        elif state == RUBBING:
            _, frame = analyser.analyse(frame)

            if rubbing:
                rub_duration += now - rub_start
                rub_start     = now
                last_rub_time = now
            else:
                if now - last_rub_time < RUB_PAUSE_TOLERANCE:
                    rub_duration += now - rub_start
                rub_start = now

            if "soap" not in steps_completed and rub_duration >= ASSUMED_SOAP_DURATION:
                print("  (soap skipped — rubbing 10s without soap step)")

            if rub_duration >= min_wash_duration:
                log_step("rub")
                state = RINSING
                print("Rubbing complete — waiting for rinse / drying zone...")

        elif state == RINSING:
            log_step("rinse")

            # Chest-width body box — visible from RINSING onwards
            body_box = get_body_zone(kp, kp_conf)
            draw_body_zone(frame, body_box)

            # Body-drying detection — wrist oscillating on torso
            active_wrist = lw_px if lw_px is not None else rw_px
            if active_wrist is not None:
                zone_hit = wrist_in_body_zone(active_wrist[0], active_wrist[1], body_box)
                if zone_hit:
                    body_dry_wrist_history.append((active_wrist[0], active_wrist[1], now))
                    if body_dry_start == 0.0:
                        body_dry_start = now
                    body_dry_duration = now - body_dry_start
                    if (body_dry_duration >= BODY_DRY_MIN_DURATION and
                            detect_oscillation(body_dry_wrist_history)):
                        if "body_drying" not in steps_completed:
                            log_step("body_drying")
                            print("  ⚠ Body drying detected — possible contamination")
                else:
                    body_dry_start    = 0.0
                    body_dry_duration = 0.0
                    body_dry_wrist_history.clear()

            # Transition to DRYING once both wrists enter the dryer zone
            if in_dry:
                state     = DRYING
                dry_start = now

        elif state == DRYING:
            # Body box stays visible until drying is confirmed
            body_box = get_body_zone(kp, kp_conf)
            draw_body_zone(frame, body_box)

            # Both wrists in zone → count. Simple.
            if in_dry:
                dry_duration += now - dry_start
            dry_start = now

            if dry_duration >= MIN_DRY_DURATION:
                log_step("dry")
                state        = RECONTAMINATION
                result_timer = now
                recontamination_contact_start = 0.0
                print("Drying complete — monitoring for recontamination...")

        elif state == RECONTAMINATION:
            recontamination_contact = in_sink_lw or in_sink_rw

            if recontamination_contact:
                if recontamination_contact_start == 0.0:
                    recontamination_contact_start = now
                if (now - recontamination_contact_start) >= RECONTAMINATION_CONFIRM_TIME:
                    if "recontamination" not in steps_completed:
                        print("  ⚠ Possible recontamination detected — wrist near tap after drying")
                        log_step("recontamination")
            else:
                recontamination_contact_start = 0.0

            if not valid_wrist_detected and (now - last_seen) > RECONTAMINATION_LEAVE_TIMEOUT:
                conclude_session()
            elif now - result_timer > RECONTAMINATION_MONITOR_TIME:
                conclude_session()

        elif state == COMPLETE:
            if now - result_timer > RESULT_DISPLAY_TIME:
                reset_session()

        if lw_px is not None:
            prev_lw = lw_px
        if rw_px is not None:
            prev_rw = rw_px

        if not valid_wrist_detected and state not in (IDLE, COMPLETE, RECONTAMINATION):
            if now - last_seen > NO_PERSON_TIMEOUT:
                print("Person left early — ending session")
                if steps_completed:
                    conclude_session()
                else:
                    result_display = "MISSED"
                    result_color   = (0, 165, 255)
                    result_timer   = now
                    state          = COMPLETE
                    print("MISSED — no steps completed")

    else:
        if state not in (IDLE, COMPLETE):
            if now - last_seen > NO_PERSON_TIMEOUT:
                print("Person left early — ending session")
                if steps_completed:
                    conclude_session()
                else:
                    result_display = "MISSED"
                    result_color   = (0, 165, 255)
                    result_timer   = now
                    state          = COMPLETE
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

    if state == RUBBING:
        technique   = analyser.get_summary()
        score_color = (0, 255, 0) if technique["technique_score"] >= 3 else (0, 165, 255)
        cv2.putText(frame, f"Technique: {technique['technique_score']}/4",
                    (10, 133), cv2.FONT_HERSHEY_SIMPLEX, 0.5, score_color, 1)

    steps_str = " → ".join(steps_completed) if steps_completed else "none"
    cv2.putText(frame, f"Steps: {steps_str}", (10, 108),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    if result_display and state == COMPLETE:
        cv2.putText(frame, result_display, (150, 280),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, result_color, 4)
        if technique_summary:
            cv2.putText(frame, f"Technique: {technique_summary['technique_score']}/4",
                        (150, 340), cv2.FONT_HERSHEY_SIMPLEX, 1.0, result_color, 2)

    cv2.putText(frame, site_name, (10, 470),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)

    cv2.imshow("Handwash Detection", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ── Cleanup ──────────────────────────────────────────────────────
cap.release()
cv2.destroyAllWindows()
analyser.hands.close()