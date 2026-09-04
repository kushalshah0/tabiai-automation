#!/usr/bin/env bash
set -o pipefail
set -e

# Sync python environment requirements
pip install -r requirements.txt

# Download required automated browser libraries
playwright install chromium
