#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
sha256sum -c FILE_HASHES.sha256
python3 -m py_compile livextv_scanner.py
python3 -m unittest discover -s tests -v
bash -n RUN_LOCAL.sh VERIFY_PACKAGE.sh
