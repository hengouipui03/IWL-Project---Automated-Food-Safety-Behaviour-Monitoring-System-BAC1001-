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
pip install flask requests ultralytics opencv-python "mediapipe==0.10.14" numpy

echo ""
echo "=== Done. Next steps ==="
echo "  conda activate handwash"
echo "  cd detection_dashboard"
echo "  python zone_setup.py --config site_config.json   # draw zones once"
echo "  python dashboard_app.py                           # terminal 1 (website)"
echo "  python detection.py --config site_config.json     # terminal 2 (camera)"
