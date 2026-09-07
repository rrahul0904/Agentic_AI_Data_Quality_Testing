#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose --profile tools run --rm dbt build --profiles-dir . "$@"

