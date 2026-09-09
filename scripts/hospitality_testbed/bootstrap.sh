#!/usr/bin/env bash
set -euo pipefail

mode="${ADE_TESTBED_MODE:-local}"
python3 scripts/hospitality_testbed/bootstrap_snowflake.py --mode "$mode" "$@"
