import cv2
import json
import os

# ── State ────────────────────────────────────────────────────────
zones        = {}
current_zone = None
drawing      = False
start_x      = start_y = 0
temp_end_x   = temp_end_y = 0

# Zone definition order
ZONE_ORDER = ["sink_basin", "tap", "soap_dispenser"]
ZONE_LABELS = {
    "sink_basin":     "SINK BASIN — click and drag to draw",
    "tap":            "TAP ZONE — click and drag to draw",
    "soap_dispenser": "SOAP DISPENSER — click and drag to draw"
}
ZONE_COLORS = {
    "sink_basin":     (0, 255, 0),    # green
    "tap":            (0, 165, 255),  # orange
    "soap_dispenser": (255, 0, 0)     # blue
}

zone_index = 0

def mouse_callback(event, x, y, flags, param):
    global drawing, start_x, start_y, temp_end_x, temp_end_y, zone_index, current_zone

    if zone_index >= len(ZONE_ORDER):
        return

    current_zone = ZONE_ORDER[zone_index]

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        start_x, start_y = x, y

    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing:
            temp_end_x, temp_end_y = x, y

    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        # Save zone as (x1, y1, x2, y2) — top-left to bottom-right
        x1, y1 = min(start_x, x), min(start_y, y)
        x2, y2 = max(start_x, x), max(start_y, y)
        zones[current_zone] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
        print(f"✔ {current_zone} saved: ({x1},{y1}) → ({x2},{y2})")
        zone_index += 1

# ── Webcam setup ─────────────────────────────────────────────────
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("Error: Could not open webcam")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

cv2.namedWindow("Zone Setup")
cv2.setMouseCallback("Zone Setup", mouse_callback)

print("\n=== ZONE SETUP ===")
print("Draw each zone by clicking and dragging on the feed.")
print("Zones: Sink Basin → Tap → Soap Dispenser\n")

# ── Main loop ────────────────────────────────────────────────────
while True:
    ret, frame = cap.read()
    if not ret:
        break

    display = frame.copy()

    # Draw all already-saved zones
    for name, z in zones.items():
        color = ZONE_COLORS[name]
        cv2.rectangle(display, (z["x1"], z["y1"]), (z["x2"], z["y2"]), color, 2)
        cv2.putText(display, name, (z["x1"] + 4, z["y1"] + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    # Draw the rectangle currently being drawn
    if drawing and zone_index < len(ZONE_ORDER):
        color = ZONE_COLORS[ZONE_ORDER[zone_index]]
        cv2.rectangle(display, (start_x, start_y), (temp_end_x, temp_end_y), color, 2)

    # Show current instruction or completion message
    if zone_index < len(ZONE_ORDER):
        label = ZONE_LABELS[ZONE_ORDER[zone_index]]
        cv2.putText(display, label, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(display, f"Zone {zone_index + 1} of {len(ZONE_ORDER)}", (10, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    else:
        cv2.putText(display, "All zones defined! Press S to save or R to redo", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

    cv2.imshow("Zone Setup", display)

    key = cv2.waitKey(1) & 0xFF

    # Save config
    if key == ord('s') and zone_index >= len(ZONE_ORDER):
        site_name = input("\nEnter site name (e.g. Factory A - Sink 1): ").strip()
        config = {
            "site_name":   site_name,
            "frame_width": 640,
            "frame_height": 480,
            "min_wash_duration": 20,
            "zones": zones
        }
        with open("site_config.json", "w") as f:
            json.dump(config, f, indent=2)
        print(f"\n✔ Config saved to site_config.json")
        print(f"  Site: {site_name}")
        print(f"  Zones: {list(zones.keys())}")
        break

    # Redo — clear all zones and restart
    elif key == ord('r'):
        zones      = {}
        zone_index = 0
        drawing    = False
        print("\nRedoing zone setup...")

    elif key == ord('q'):
        print("Setup cancelled.")
        break

# ── Cleanup ──────────────────────────────────────────────────────
cap.release()
cv2.destroyAllWindows()