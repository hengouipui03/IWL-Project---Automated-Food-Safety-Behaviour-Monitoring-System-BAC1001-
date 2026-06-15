import cv2
from ultralytics import YOLO

# ── Load YOLOv8 Pose model ───────────────────────────────────────
# First run will auto-download the model weights (~6MB)
model = YOLO("yolov8n-pose.pt")

# ── Webcam setup ─────────────────────────────────────────────────
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("Error: Could not open webcam")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

print("Running YOLOv8 Pose — press Q to quit")

# ── Keypoint indices (YOLOv8 uses 17 COCO keypoints) ────────────
# 0=nose, 1=left eye, 2=right eye, 3=left ear, 4=right ear
# 5=left shoulder, 6=right shoulder, 7=left elbow, 8=right elbow
# 9=left wrist, 10=right wrist, 11=left hip, 12=right hip
# 13=left knee, 14=right knee, 15=left ankle, 16=right ankle
LEFT_WRIST  = 9
RIGHT_WRIST = 10

# ── Main loop ────────────────────────────────────────────────────
while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to read frame")
        break

    # Run YOLOv8 Pose on the frame
    results = model(frame, verbose=False)

    # results[0].keypoints.xy contains keypoint (x,y) per person
    keypoints = results[0].keypoints

    if keypoints is not None and len(keypoints) > 0:
        # Take the first detected person only (single person MVP)
        kp = keypoints.xy[0]  # shape: [17, 2]

        lw_px = (int(kp[LEFT_WRIST][0]),  int(kp[LEFT_WRIST][1]))
        rw_px = (int(kp[RIGHT_WRIST][0]), int(kp[RIGHT_WRIST][1]))

        # Print wrist coords to terminal
        print(f"L wrist: {lw_px}  |  R wrist: {rw_px}", end="\r")

        # Draw wrist dots
        cv2.circle(frame, lw_px, 10, (0, 255, 255), -1)  # yellow = left
        cv2.circle(frame, rw_px, 10, (0, 165, 255), -1)  # orange = right

        cv2.putText(frame, "Person detected", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    else:
        cv2.putText(frame, "No person detected", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

    # Draw YOLOv8 skeleton on frame
    annotated = results[0].plot()
    cv2.imshow("YOLOv8 Pose", annotated)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ── Cleanup ──────────────────────────────────────────────────────
cap.release()
cv2.destroyAllWindows()