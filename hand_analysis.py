import cv2
import mediapipe as mp
import time
from collections import deque

class HandAnalyser:

    def __init__(self):
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )

        # Technique tracking
        self.palm_up_detected = False
        self.palm_down_detected = False
        self.fingers_spread_detected = False
        self.wrist_rubbed = False
        self.technique_history = deque(maxlen=30)  # last 30 frames

        self.technique_thresholds = {
            "palm_up": 1.5,
            "palm_down": 1.5,
            "fingers_spread": 1.0,
            "wrist_rubbed": 1.5
        }
        self.technique_start_times = {
            "palm_up": None,
            "palm_down": None,
            "fingers_spread": None,
            "wrist_rubbed": None
        }

    def reset(self):
        self.palm_up_detected = False
        self.palm_down_detected = False
        self.fingers_spread_detected = False
        self.wrist_rubbed = False
        self.technique_history.clear()
        for key in self.technique_start_times:
            self.technique_start_times[key] = None

    def _update_sustained_detection(self, technique_name, is_detected, now):
        if is_detected:
            if self.technique_start_times[technique_name] is None:
                self.technique_start_times[technique_name] = now
            return (now - self.technique_start_times[technique_name]) >= self.technique_thresholds[technique_name]

        self.technique_start_times[technique_name] = None
        return False

    def _is_palm_up(self, hand_landmarks, handedness):
        # Palm up = wrist z > middle finger z (hand rotated toward camera)
        wrist_z = hand_landmarks.landmark[0].z
        middle_z = hand_landmarks.landmark[9].z
        if handedness == "Right":
            return wrist_z > middle_z
        else:
            return wrist_z < middle_z

    def _is_palm_down(self, hand_landmarks, handedness):
        return not self._is_palm_up(hand_landmarks, handedness)

    def _fingers_spread(self, hand_landmarks):
        # Check distance between adjacent fingertips
        # If spread, fingertips are far apart relative to hand size
        fingertips = [4, 8, 12, 16, 20]  # thumb, index, middle, ring, pinky
        wrist = hand_landmarks.landmark[0]
        middle_base = hand_landmarks.landmark[9]

        # Hand size reference — distance from wrist to middle base
        hand_size = abs(wrist.y - middle_base.y)
        if hand_size < 0.01:
            return False

        # Check spread between index and pinky fingertips
        index_tip = hand_landmarks.landmark[8]
        pinky_tip = hand_landmarks.landmark[20]
        spread = abs(index_tip.x - pinky_tip.x)

        return spread > hand_size * 1.2

    def _wrist_area_rubbed(self, hand_landmarks):
        # Wrist rubbing detected when wrist landmark y is close to opposite hand's palm
        wrist = hand_landmarks.landmark[0]
        return wrist.y > 0.6  # wrist is low in frame — being presented for rubbing

    def analyse(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb)

        technique = {
            "hands_detected": 0,
            "palm_up": False,
            "palm_down": False,
            "fingers_spread": False,
            "wrist_rubbed": False,
            "both_hands": False,
        }

        if not results.multi_hand_landmarks:
            for key in self.technique_start_times:
                self.technique_start_times[key] = None
            return technique, frame

        now = time.time()
        technique["hands_detected"] = len(results.multi_hand_landmarks)
        technique["both_hands"] = len(results.multi_hand_landmarks) == 2

        for i, hand_landmarks in enumerate(results.multi_hand_landmarks):
            handedness = results.multi_handedness[i].classification[0].label

            # Draw landmarks on frame
            self.mp_drawing.draw_landmarks(
                frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS
            )

            # Check technique
            if self._is_palm_up(hand_landmarks, handedness):
                technique["palm_up"] = True

            if self._is_palm_down(hand_landmarks, handedness):
                technique["palm_down"] = True

            if self._fingers_spread(hand_landmarks):
                technique["fingers_spread"] = True

            if self._wrist_area_rubbed(hand_landmarks):
                technique["wrist_rubbed"] = True

        if self._update_sustained_detection("palm_up", technique["palm_up"], now):
            self.palm_up_detected = True

        if self._update_sustained_detection("palm_down", technique["palm_down"], now):
            self.palm_down_detected = True

        if self._update_sustained_detection("fingers_spread", technique["fingers_spread"], now):
            self.fingers_spread_detected = True

        if self._update_sustained_detection("wrist_rubbed", technique["wrist_rubbed"], now):
            self.wrist_rubbed = True

        self.technique_history.append(technique)
        return technique, frame

    def get_summary(self):
        # Called at end of rubbing session to summarise technique
        missing = []
        if not self.palm_up_detected:
            missing.append("palm up not detected")
        if not self.palm_down_detected:
            missing.append("palm down not detected")
        if not self.fingers_spread_detected:
            missing.append("fingers spread not detected")
        if not self.wrist_rubbed:
            missing.append("wrist area not rubbed")

        return {
            "palm_up": self.palm_up_detected,
            "palm_down": self.palm_down_detected,
            "fingers_spread": self.fingers_spread_detected,
            "wrist_rubbed": self.wrist_rubbed,
            "missing": missing,
            "technique_score": 4 - len(missing)  # out of 4
        }


# ── Standalone test — run this file directly to test ─────────────
if __name__ == "__main__":
    import time

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    cv2.namedWindow("Hand Analysis Test", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Hand Analysis Test", 1280, 960)

    analyser = HandAnalyser()
    print("Running hand analysis test — press Q to quit\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        technique, frame = analyser.analyse(frame)

        # HUD
        cv2.putText(frame, f"Hands detected: {technique['hands_detected']}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame, f"Both hands: {technique['both_hands']}", (10, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if technique["both_hands"] else (0, 0, 255), 2)
        cv2.putText(frame, f"Palm up:    {technique['palm_up']}", (10, 86),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if technique["palm_up"] else (0, 0, 255), 2)
        cv2.putText(frame, f"Palm down:  {technique['palm_down']}", (10, 114),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if technique["palm_down"] else (0, 0, 255), 2)
        cv2.putText(frame, f"Fingers spread: {technique['fingers_spread']}", (10, 142),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if technique["fingers_spread"] else (0, 0, 255), 2)
        cv2.putText(frame, f"Wrist rubbed:   {technique['wrist_rubbed']}", (10, 170),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if technique["wrist_rubbed"] else (0, 0, 255), 2)

        # Summary
        summary = analyser.get_summary()
        cv2.putText(frame, f"Technique score: {summary['technique_score']}/4", (10, 210),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        cv2.imshow("Hand Analysis Test", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    summary = analyser.get_summary()
    print("\n── Final Summary ──")
    print(f"Technique score: {summary['technique_score']}/4")
    print(f"Missing: {summary['missing']}")

    cap.release()
    cv2.destroyAllWindows()
