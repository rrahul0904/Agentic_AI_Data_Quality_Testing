#!/usr/bin/env bash
set -euo pipefail

python3 scripts/hospitality_testbed/run_e2e.py \
  --mode local \
  --preset "${ADE_TESTBED_SCALE:-tiny}" \
  --seed "${ADE_TESTBED_SEED:-42}" \
  "$@"
