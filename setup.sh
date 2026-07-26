#!/usr/bin/env bash
# One-time setup for the Food Safety Monitoring project.
set -e
echo "=== Food Safety Monitoring - setup ==="

if ! command -v conda &> /dev/null; then
  echo "Conda not found. Install Miniconda: https://docs.conda.io/en/latest/miniconda.html"
  exit 1
fi

echo "Creating conda env 'handwash' (Python 3.11)..."
conda create -n handwash python=3.11 -y

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate handwash
echo "Installing packages..."
pip install flask requests ultralytics opencv-python "mediapipe==0.10.14" numpy paho-mqtt imageio-ffmpeg

echo ""
echo "=== Done. Next steps ==="
echo "  conda activate handwash"
echo "  cd detection  && python zone_setup.py --config site_config.json   # draw zones once"
echo "  cd dashboard  && python dashboard_app.py                          # terminal 1 (website)"
echo "  cd detection  && python detection.py --config site_config.json    # terminal 2 (camera + sensors)"
echo ""
echo "Note: the M5Stack sensor code in sensors/ runs on the M5Stack devices"
echo "themselves (via UIFlow), not on this computer, and is not installed here."
