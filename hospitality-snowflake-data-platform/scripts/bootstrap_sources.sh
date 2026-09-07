#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m data_generator.generate_source_ddl --root .
docker compose up -d postgres

