import cv2
import json

# ── Zone types ───────────────────────────────────────────────────
ZONE_TYPES = {
    "1": {"key": "sink_tap",       "label": "SINK / TAP",      "color": (0, 255, 0)},
    "2": {"key": "soap_dispenser", "label": "SOAP DISPENSER",  "color": (255, 0, 0)},
    "3": {"key": "dryer",          "label": "DRYER / TOWEL",   "color": (255, 0, 255)},
}

# ── State ────────────────────────────────────────────────────────
zones       = {"sink_tap": [], "soap_dispenser": [], "dryer": []}
drawing     = False
start_x     = start_y = 0
temp_end_x  = temp_end_y = 0
active_type = None
save_flag   = False

def mouse_callback(event, x, y, flags, param):
    global drawing, start_x, start_y, temp_end_x, temp_end_y

    if active_type is None:
        return

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        start_x, start_y = x, y

    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing:
            temp_end_x, temp_end_y = x, y

    elif event == cv2.EVENT_LBUTTONUP:
        if drawing:
            drawing = False
            x1, y1 = min(start_x, x), min(start_y, y)
            x2, y2 = max(start_x, x), max(start_y, y)
            if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
                print("Zone too small — try again")
                return
            zones[active_type].append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
            print(f"✔ {active_type} #{len(zones[active_type])} saved: ({x1},{y1}) → ({x2},{y2})")

# ── Webcam setup ─────────────────────────────────────────────────
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("Error: Could not open webcam")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

print("\n=== ZONE SETUP ===")
print("  1 — Draw SINK / TAP zone")
print("  2 — Draw SOAP DISPENSER zone")
print("  3 — Draw DRYER / TOWEL zone")
print("  U — Undo last zone")
print("  S — Save and finish")
print("  Q — Quit without saving\n")

# ── Window + mouse — must come just before the loop ──────────────
cv2.namedWindow("Zone Setup", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Zone Setup", 1920, 1080)
cv2.setMouseCallback("Zone Setup", mouse_callback)

# ── Main loop ────────────────────────────────────────────────────
while True:
    ret, frame = cap.read()
    if not ret:
        break

    display = frame.copy()

    # Draw saved zones
    for zone_type, zone_list in zones.items():
        color = next(v["color"] for v in ZONE_TYPES.values() if v["key"] == zone_type)
        for i, z in enumerate(zone_list):
            cv2.rectangle(display, (z["x1"], z["y1"]), (z["x2"], z["y2"]), color, 2)
            cv2.putText(display, f"{zone_type} #{i+1}", (z["x1"] + 4, z["y1"] + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

    # Draw zone being dragged
    if drawing and active_type:
        color = next(v["color"] for v in ZONE_TYPES.values() if v["key"] == active_type)
        cv2.rectangle(display, (start_x, start_y), (temp_end_x, temp_end_y), color, 2)

    # HUD
    if active_type:
        label = next(v["label"] for v in ZONE_TYPES.values() if v["key"] == active_type)
        cv2.putText(display, f"Drawing: {label}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    else:
        cv2.putText(display, "Press 1, 2, or 3 to select zone type", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 2)

    cv2.putText(display, "S = Save   Q = Quit   U = Undo", (10, 460),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    # Zone counts
    y_offset = 440
    for zone_type, zone_list in zones.items():
        color = next(v["color"] for v in ZONE_TYPES.values() if v["key"] == zone_type)
        cv2.putText(display, f"{zone_type}: {len(zone_list)}", (480, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        y_offset -= 18
    cv2.imshow("Zone Setup", display)
    

    key = cv2.waitKey(1) & 0xFF

    if key == ord('1'):
        active_type = "sink_tap"
        print("Mode: SINK / TAP")
    elif key == ord('2'):
        active_type = "soap_dispenser"
        print("Mode: SOAP DISPENSER")
    elif key == ord('3'):
        active_type = "dryer"
        print("Mode: DRYER / TOWEL")

    elif key == ord('u') and active_type and zones[active_type]:
        removed = zones[active_type].pop()
        print(f"✖ Removed last {active_type}")

    elif key == ord('s'):
        total = sum(len(v) for v in zones.values())
        if total == 0:
            print("No zones drawn yet")
        else:
            save_flag = True
            break

    elif key == ord('q'):
        print("Setup cancelled.")
        cap.release()
        cv2.destroyAllWindows()
        exit()

# ── Save after loop exits ─────────────────────────────────────────
if save_flag:
    cap.release()
    cv2.destroyAllWindows()
    site_name = input("Enter site name (e.g. Factory A - Sink Row 1): ").strip()
    config = {
        "site_name":         site_name,
        "frame_width":       640,
        "frame_height":      480,
        "min_wash_duration": 20,
        "zones":             zones
    }
    with open("site_config.json", "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n✔ Saved to site_config.json")
    for k, v in zones.items():
        if v:
            print(f"  {k}: {len(v)} zone(s)")