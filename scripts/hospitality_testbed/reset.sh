#!/usr/bin/env bash
set -euo pipefail

: "${ADE_SNOWFLAKE_DATABASE:=HOSPITALITY_TESTBED}"
python3 scripts/hospitality_testbed/reset_testbed.py --confirm-database "$ADE_SNOWFLAKE_DATABASE" "$@"
