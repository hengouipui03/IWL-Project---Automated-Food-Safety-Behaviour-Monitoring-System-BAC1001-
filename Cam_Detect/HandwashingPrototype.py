import cv2
import time
from collections import deque
from ultralytics import YOLO

model = YOLO("yolov8n-pose.pt")
cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)

if not cap.isOpened():
    print("Error: Could not open webcam")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

LEFT_WRIST = 9
RIGHT_WRIST = 10

SOAP_ZONE = (50, 150, 180, 300)
TAP_ZONE = (250, 100, 380, 220)
SINK_ZONE = (180, 230, 520, 460)

# Timing parameters
WASH_REQUIRED_SECONDS = 20
MIN_ZONE_DURATION = 0.5
GRACE_PERIOD = 1.0
MIN_KEYPOINT_CONFIDENCE = 0.5

# State tracking
state = "PREPARING"
accumulated_wash_time = 0
last_in_sink_time = None

# Track whether soap and tap have been used (in any order)
soap_used = False
tap_used = False

zone_entry_times = {"soap": None, "tap": None, "sink": None}

detection_history = {
    "soap": deque(maxlen=15),
    "tap": deque(maxlen=15),
    "sink": deque(maxlen=15)
}

# User-friendly status messages
STATUS_MESSAGES = {
    "PREPARING": "Preparing to wash hands",
    "WASHING": "Washing hands",
    "FINISHING": "Finishing - turn off tap",
    "COMPLETED": "✓ Hand washing complete!"
}

# Simple zone labels
ZONE_LABELS = {
    "SOAP": "Soap",
    "TAP": "Tap",
    "SINK": "Washing Area"
}


def draw_zone(frame, zone, label, active=False):
    """Draw zone with color coding based on activity"""
    x1, y1, x2, y2 = zone
    color = (0, 255, 0) if active else (255, 255, 255)
    thickness = 3 if active else 2
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
    cv2.putText(frame, label, (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


def draw_progress_bar(frame, progress, x, y, width=200, height=30):
    """Draw a visual progress bar for washing time"""
    cv2.rectangle(frame, (x, y), (x + width, y + height), (50, 50, 50), -1)
    
    fill_width = int(width * min(progress, 1.0))
    color = (0, 255, 0) if progress >= 1.0 else (0, 165, 255)
    cv2.rectangle(frame, (x, y), (x + fill_width, y + height), color, -1)
    
    cv2.rectangle(frame, (x, y), (x + width, y + height), (255, 255, 255), 2)
    
    percentage = int(progress * 100)
    text = f"{percentage}%" if progress < 1.0 else "DONE"
    text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
    text_x = x + (width - text_size[0]) // 2
    text_y = y + (height + text_size[1]) // 2
    cv2.putText(frame, text, (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)


def draw_checklist_item(frame, text, completed, x, y):
    """Draw a checklist item with checkmark or empty box"""
    if completed:
        symbol = "✓"
        color = (0, 255, 0)
    else:
        symbol = "○"
        color = (150, 150, 150)
    
    cv2.putText(frame, f"{symbol} {text}", (x, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def inside_zone(point, zone, confidence=1.0):
    if confidence < MIN_KEYPOINT_CONFIDENCE:
        return False
    x, y = point
    x1, y1, x2, y2 = zone
    return x1 <= x <= x2 and y1 <= y <= y2


def get_smoothed_detection(zone_name):
    if len(detection_history[zone_name]) == 0:
        return False
    return sum(detection_history[zone_name]) / len(detection_history[zone_name]) > 0.6


def check_both_hands_in_zone(lw_px, rw_px, lw_conf, rw_conf, zone):
    left_in = inside_zone(lw_px, zone, lw_conf)
    right_in = inside_zone(rw_px, zone, rw_conf)
    return left_in and right_in


def update_handwashing_state(current_state, hands_data):
    global accumulated_wash_time, last_in_sink_time, zone_entry_times
    global soap_used, tap_used
    
    current_time = time.time()
    
    detection_history["soap"].append(hands_data["soap"])
    detection_history["tap"].append(hands_data["tap"])
    detection_history["sink"].append(hands_data["sink"])
    
    smooth_soap = get_smoothed_detection("soap")
    smooth_tap = get_smoothed_detection("tap")
    smooth_sink = get_smoothed_detection("sink")
    
    if current_state == "PREPARING":
        # Check if soap has been used
        if smooth_soap and not soap_used:
            if zone_entry_times["soap"] is None:
                zone_entry_times["soap"] = current_time
            elif current_time - zone_entry_times["soap"] >= MIN_ZONE_DURATION:
                soap_used = True
                zone_entry_times["soap"] = None
        elif not smooth_soap:
            zone_entry_times["soap"] = None
        
        # Check if tap has been used
        if smooth_tap and not tap_used:
            if zone_entry_times["tap"] is None:
                zone_entry_times["tap"] = current_time
            elif current_time - zone_entry_times["tap"] >= MIN_ZONE_DURATION:
                tap_used = True
                zone_entry_times["tap"] = None
        elif not smooth_tap:
            zone_entry_times["tap"] = None
        
        # Once BOTH soap and tap have been used (in any order), check for sink
        if soap_used and tap_used:
            if smooth_sink:
                if zone_entry_times["sink"] is None:
                    zone_entry_times["sink"] = current_time
                elif current_time - zone_entry_times["sink"] >= MIN_ZONE_DURATION:
                    zone_entry_times["sink"] = None
                    last_in_sink_time = current_time
                    return "WASHING"
            else:
                zone_entry_times["sink"] = None
    
    elif current_state == "WASHING":
        if smooth_sink:
            if last_in_sink_time is not None:
                accumulated_wash_time += current_time - last_in_sink_time
            last_in_sink_time = current_time
            
            if accumulated_wash_time >= WASH_REQUIRED_SECONDS:
                return "FINISHING"
        else:
            if last_in_sink_time is not None:
                time_since_left = current_time - last_in_sink_time
                
                if time_since_left > GRACE_PERIOD:
                    accumulated_wash_time = 0
                    last_in_sink_time = None
                    return "PREPARING"
    
    elif current_state == "FINISHING":
        if smooth_tap:
            if zone_entry_times["tap"] is None:
                zone_entry_times["tap"] = current_time
            elif current_time - zone_entry_times["tap"] >= MIN_ZONE_DURATION:
                return "COMPLETED"
        else:
            zone_entry_times["tap"] = None
    
    return current_state


print("Hand Washing Compliance Monitor - Press Q to quit, R to reset")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to read frame")
        break

    results = model(frame, verbose=False)
    annotated = results[0].plot()

    keypoints = results[0].keypoints
    hands_data = {"soap": False, "tap": False, "sink": False}

    active_zones = {"SOAP": False, "TAP": False, "SINK": False}
    
    if keypoints is not None and len(keypoints) > 0:
        kp_xy = keypoints.xy[0]
        kp_conf = keypoints.conf[0]

        lw_px = (int(kp_xy[LEFT_WRIST][0]), int(kp_xy[LEFT_WRIST][1]))
        rw_px = (int(kp_xy[RIGHT_WRIST][0]), int(kp_xy[RIGHT_WRIST][1]))
        lw_conf = float(kp_conf[LEFT_WRIST])
        rw_conf = float(kp_conf[RIGHT_WRIST])

        cv2.circle(annotated, lw_px, 8, (0, 255, 255), -1)
        cv2.circle(annotated, rw_px, 8, (0, 165, 255), -1)

        hands_data["soap"] = check_both_hands_in_zone(lw_px, rw_px, lw_conf, rw_conf, SOAP_ZONE)
        hands_data["tap"] = inside_zone(lw_px, TAP_ZONE, lw_conf) or inside_zone(rw_px, TAP_ZONE, rw_conf)
        hands_data["sink"] = check_both_hands_in_zone(lw_px, rw_px, lw_conf, rw_conf, SINK_ZONE)

        active_zones["SOAP"] = get_smoothed_detection("soap")
        active_zones["TAP"] = get_smoothed_detection("tap")
        active_zones["SINK"] = get_smoothed_detection("sink")

        state = update_handwashing_state(state, hands_data)

    # Draw zones with activity highlighting
    draw_zone(annotated, SOAP_ZONE, ZONE_LABELS["SOAP"], active_zones["SOAP"])
    draw_zone(annotated, TAP_ZONE, ZONE_LABELS["TAP"], active_zones["TAP"])
    draw_zone(annotated, SINK_ZONE, ZONE_LABELS["SINK"], active_zones["SINK"])

    # Create status panel background
    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (640, 150), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.5, annotated, 0.5, 0, annotated)

    # Display current status
    instruction = STATUS_MESSAGES[state]
    
    if state == "COMPLETED":
        color = (0, 255, 0)
        font_scale = 1.0
    else:
        color = (255, 255, 255)
        font_scale = 0.8
    
    cv2.putText(annotated, instruction, (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 2)

    # Show checklist during preparation phase
    if state == "PREPARING":
        draw_checklist_item(annotated, "Used soap", soap_used, 20, 75)
        draw_checklist_item(annotated, "Turned on tap", tap_used, 20, 105)
        
        if soap_used and tap_used:
            cv2.putText(annotated, "→ Now place hands in washing area", (20, 135),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    # Show washing progress when in washing state
    if state == "WASHING" or state == "FINISHING":
        progress = accumulated_wash_time / WASH_REQUIRED_SECONDS
        
        draw_progress_bar(annotated, progress, 20, 75)
        
        seconds_remaining = max(0, WASH_REQUIRED_SECONDS - accumulated_wash_time)
        if seconds_remaining > 0:
            time_text = f"{int(seconds_remaining)} seconds remaining"
        else:
            time_text = "Washing time complete!"
        
        cv2.putText(annotated, time_text, (240, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        if state == "FINISHING":
            cv2.putText(annotated, "→ Turn off tap to complete", (20, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    # Completion banner
    if state == "COMPLETED":
        overlay = annotated.copy()
        cv2.rectangle(overlay, (0, 400), (640, 480), (0, 200, 0), -1)
        cv2.addWeighted(overlay, 0.3, annotated, 0.7, 0, annotated)
        
        cv2.putText(annotated, "HAND WASHING COMPLETE!", (80, 450),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 0), 3)

    cv2.imshow("Hand Washing Compliance Monitor", annotated)

    key = cv2.waitKey(1) & 0xFF

    if key == ord('q'):
        break

    if key == ord('r'):
        state = "PREPARING"
        accumulated_wash_time = 0
        last_in_sink_time = None
        soap_used = False
        tap_used = False
        zone_entry_times = {"soap": None, "tap": None, "sink": None}
        detection_history = {
            "soap": deque(maxlen=15),
            "tap": deque(maxlen=15),
            "sink": deque(maxlen=15)
        }
        print("System reset - ready for next employee")

cap.release()
cv2.destroyAllWindows()