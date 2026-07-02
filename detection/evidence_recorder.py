"""
Evidence video recorder for detection.py.

It records the annotated OpenCV frame, saves it into dashboard/static/evidence/,
and converts the final file to browser-playable H.264 MP4 when imageio-ffmpeg is installed.
"""

import os
import subprocess
from datetime import datetime

import cv2

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None


class EvidenceRecorder:
    def __init__(self, evidence_dir=None, url_prefix="/static/evidence", fps=20.0):
        # This file is expected to live inside the detection/ folder.
        # The evidence folder is inside dashboard/static/evidence/ so Flask can serve it.
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(base_dir)

        self.evidence_dir = evidence_dir or os.path.join(
            project_root,
            "dashboard",
            "static",
            "evidence"
        )
        self.url_prefix = url_prefix.rstrip("/")
        self.fps = fps

        os.makedirs(self.evidence_dir, exist_ok=True)

        self.video_writer = None
        self.evidence_url = None
        self.evidence_path = None
        self.raw_evidence_path = None

    def start(self, frame):
        """Start recording a new evidence video for the current session."""
        if self.video_writer is not None:
            return self.evidence_url

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_filename = f"incident_{timestamp}.mp4"
        raw_filename = f"incident_{timestamp}_raw.mp4"

        self.evidence_path = os.path.join(self.evidence_dir, final_filename)
        self.raw_evidence_path = os.path.join(self.evidence_dir, raw_filename)
        self.evidence_url = f"{self.url_prefix}/{final_filename}"

        height, width = frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        # OpenCV records a temporary MP4 first. At the end of the session,
        # we convert it to H.264 MP4 so Chrome can play it in the dashboard.
        self.video_writer = cv2.VideoWriter(
            self.raw_evidence_path,
            fourcc,
            self.fps,
            (width, height)
        )

        if not self.video_writer.isOpened():
            print("  -> evidence recording failed to start")
            self.video_writer = None
            self.evidence_url = None
            self.evidence_path = None
            self.raw_evidence_path = None
            return None

        print(f"Recording evidence video: {self.evidence_url}")
        return self.evidence_url

    def write(self, frame):
        """Write one frame to the active evidence video, if recording is active."""
        if self.video_writer is not None:
            self.video_writer.write(frame)

    def stop(self, keep=True):
        """
        Stop recording and return the evidence URL if the video should be kept.

        keep=True:
            Convert the temporary video to browser-playable H.264 MP4 and keep it.
        keep=False:
            Delete the temporary/final video and return None.
        """
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None

        if not keep:
            self._safe_remove(self.raw_evidence_path)
            self._safe_remove(self.evidence_path)
            self.evidence_url = None
            self.evidence_path = None
            self.raw_evidence_path = None
            return None

        if self.raw_evidence_path and self.evidence_path:
            print("Converting evidence video for browser playback...")
            converted = self._convert_to_browser_mp4(
                self.raw_evidence_path,
                self.evidence_path
            )

            if converted:
                self._safe_remove(self.raw_evidence_path)
                print("Evidence video saved")
            else:
                # Fallback: keep the raw recording so evidence is not lost,
                # but Chrome may not be able to play it until conversion works.
                try:
                    if os.path.exists(self.evidence_path):
                        os.remove(self.evidence_path)
                    os.rename(self.raw_evidence_path, self.evidence_path)
                except OSError:
                    pass
                print("Evidence video saved, but it may not play in Chrome until conversion is fixed")

            self.raw_evidence_path = None

        return self.evidence_url

    def clear_reference(self):
        """Clear recorder references without deleting an already saved evidence video."""
        self.evidence_url = None
        self.evidence_path = None
        self.raw_evidence_path = None

    def reset(self, discard=False):
        """Stop any active recording and clear the current evidence reference.

        This does not delete an already finalised evidence video. It only
        discards an active/raw recording when discard=True.
        """
        if self.video_writer is not None:
            self.stop(keep=not discard)
        elif discard and self.raw_evidence_path:
            self._safe_remove(self.raw_evidence_path)
        self.clear_reference()

    def _convert_to_browser_mp4(self, input_path, output_path):
        """Convert OpenCV's MP4 output into browser-playable H.264 MP4."""
        if imageio_ffmpeg is None:
            print("  -> browser MP4 conversion skipped: run `py -3.12 -m pip install imageio-ffmpeg`")
            return False

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i", input_path,
            "-vcodec", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",
            output_path,
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            print("  -> browser MP4 conversion failed")
            if result.stderr:
                print(result.stderr[-500:])
            return False

        return os.path.exists(output_path) and os.path.getsize(output_path) > 0

    @staticmethod
    def _safe_remove(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
