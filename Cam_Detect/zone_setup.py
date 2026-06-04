import cv2
import argparse
import json
import os

# ── Zone types ───────────────────────────────────────────────────
ZONE_TYPES = {
    "1": {"key": "sink_tap",       "label": "SINK / TAP",      "color": (0, 255, 0)},
    "2": {"key": "soap_dispenser", "label": "SOAP DISPENSER",  "color": (255, 0, 0)},
    "3": {"key": "dryer",          "label": "DRYER / TOWEL",   "color": (255, 0, 255)},
}

def parse_camera_source(source):
    if isinstance(source, str) and source.isdigit():
        return int(source)
    return source

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="site_config.json")
parser.add_argument("--camera-source", default=None)
args = parser.parse_args()

config_path = args.config
existing_config = {}

if os.path.exists(config_path):
    with open(config_path, "r") as f:
        existing_config = json.load(f)

camera_source = parse_camera_source(args.camera_source if args.camera_source is not None else existing_config.get("camera_source", 0))
frame_width = existing_config.get("frame_width", 640)
frame_height = existing_config.get("frame_height", 480)
site_name = existing_config.get("site_name", "")
camera_id = existing_config.get("camera_id", "")

# ── State ────────────────────────────────────────────────────────
zones       = existing_config.get("zones", {"sink_tap": [], "soap_dispenser": [], "dryer": []})
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
if isinstance(camera_source, int):
    cap = cv2.VideoCapture(camera_source, cv2.CAP_DSHOW)
else:
    cap = cv2.VideoCapture(camera_source)

if not cap.isOpened():
    print(f"Error: Could not open camera source {camera_source}")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)

print("\n=== ZONE SETUP ===")
print(f"Config: {config_path}")
print(f"Camera source: {camera_source}")
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

    site_prompt = f"Enter site name (e.g. Factory A - Sink Row 1){f' [{site_name}]' if site_name else ''}: "
    new_site_name = input(site_prompt).strip()
    if new_site_name:
        site_name = new_site_name
    if not site_name:
        site_name = "Unnamed Site"

    camera_prompt = f"Enter camera ID (e.g. camera_01){f' [{camera_id}]' if camera_id else ''}: "
    new_camera_id = input(camera_prompt).strip()
    if new_camera_id:
        camera_id = new_camera_id
    if not camera_id:
        camera_id = site_name

    config = {
        "site_name":         site_name,
        "camera_id":         camera_id,
        "camera_source":     camera_source,
        "frame_width":       frame_width,
        "frame_height":      frame_height,
        "min_wash_duration": 20,
        "zones":             zones
    }

    config_dir = os.path.dirname(config_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\n✔ Saved to {config_path}")
    for k, v in zones.items():
        if v:
            print(f"  {k}: {len(v)} zone(s)")
