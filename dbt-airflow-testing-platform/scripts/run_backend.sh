#!/usr/bin/env bash
# Run in its own terminal. This is the ADE Test Control Tower API + UI.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dbt_demo_project/warehouse
cd backend
source ../.venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
