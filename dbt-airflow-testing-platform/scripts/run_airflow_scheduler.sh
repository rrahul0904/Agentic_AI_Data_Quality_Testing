#!/usr/bin/env bash
# Run in its own terminal, alongside run_airflow_webserver.sh. Runs the
# scheduler and triggerer with --skip-serve-logs: their internal log-serving
# gunicorn side-processes crash-loop in the same sandboxed-fork environments
# the webserver does, and we don't need remote log serving for a single-node
# SequentialExecutor demo.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/ade_env.sh
source .airflow_venv/bin/activate

trap 'kill 0' EXIT
airflow triggerer --skip-serve-logs &
airflow scheduler --skip-serve-logs &
wait
