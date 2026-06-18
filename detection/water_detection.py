import cv2
import numpy as np
from collections import deque


class WaterMovementDetector:
    def __init__(
        self,
        motion_threshold=8,
        min_motion_ratio=0.006,
        history_len=8,
        required_active_frames=3
    ):
        self.motion_threshold = motion_threshold
        self.min_motion_ratio = min_motion_ratio
        self.history = deque(maxlen=history_len)
        self.required_active_frames = required_active_frames
        self.prev_gray = {}

    def update(self, frame, zones):
        water_zones = zones.get("water_stream", [])

        if not water_zones:
            return False

        active_scores = []

        for idx, z in enumerate(water_zones):
            x1, y1, x2, y2 = z["x1"], z["y1"], z["x2"], z["y2"]
            roi = frame[y1:y2, x1:x2]

            if roi.size == 0:
                continue

            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)

            if idx not in self.prev_gray:
                self.prev_gray[idx] = gray
                continue

            diff = cv2.absdiff(gray, self.prev_gray[idx])
            self.prev_gray[idx] = gray

            _, thresh = cv2.threshold(
                diff,
                self.motion_threshold,
                255,
                cv2.THRESH_BINARY
            )

            kernel = np.ones((3, 3), np.uint8)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

            motion_ratio = cv2.countNonZero(thresh) / thresh.size
            active_scores.append(motion_ratio > self.min_motion_ratio)

        if not active_scores:
            self.history.append(False)
        else:
            self.history.append(any(active_scores))

        return sum(self.history) >= self.required_active_frames
