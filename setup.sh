#!/usr/bin/env bash
# One-time setup for the Food Safety Monitoring project.
# Creates a Python 3.11 conda env and installs everything needed.
set -e

echo "=== Food Safety Monitoring — setup ==="

if ! command -v conda &> /dev/null; then
  echo "Conda not found. Install Miniconda first: https://docs.conda.io/en/latest/miniconda.html"
  exit 1
fi

echo "Creating conda env 'handwash' (Python 3.11)..."
conda create -n handwash python=3.11 -y

echo "Installing packages..."
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate handwash
pip install flask requests ultralytics opencv-python "mediapipe==0.10.14" numpy

echo ""
echo "=== Done. ==="
echo "Next:"
echo "  conda activate handwash"
echo "  python zone_setup.py --config site_config.json   # draw zones once"
echo "  python dashboard_app.py                            # terminal 1"
echo "  python detection.py --config site_config.json      # terminal 2"
