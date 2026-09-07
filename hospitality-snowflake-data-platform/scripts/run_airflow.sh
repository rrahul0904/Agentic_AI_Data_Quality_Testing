#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up airflow-init
docker compose up -d airflow-webserver airflow-scheduler

