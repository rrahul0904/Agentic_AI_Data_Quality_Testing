#!/usr/bin/env bash
# Run in its own terminal. Uses --debug (Flask's built-in dev server) instead
# of the default gunicorn workers: gunicorn's forked workers SIGSEGV
# immediately in some sandboxed/macOS setups. Fine for local dev; for a real
# deployment run behind gunicorn/systemd on Linux as normal.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/ade_env.sh
source .airflow_venv/bin/activate
airflow webserver --debug --port 8080
