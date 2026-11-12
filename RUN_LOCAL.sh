#!/usr/bin/env bash
set -euo pipefail
python -m pip install -r requirements.txt
python -m playwright install chromium
python livextv_scanner.py