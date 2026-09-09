#!/usr/bin/env bash
set -euo pipefail

python3 scripts/hospitality_testbed/certify_with_ade.py --mode "${ADE_TESTBED_MODE:-live}" "$@"
python3 scripts/hospitality_testbed/generate_final_report.py
