#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON="$(command -v python3)"; fi
export PYTHONPATH="$ROOT/src"
export ADE_DEMO_MODE="${ADE_DEMO_MODE:-true}"
export ADE_DEMO_PROJECT="${ADE_DEMO_PROJECT:-$ROOT/hospitality-snowflake-data-platform}"
export ADE_QUALITY_DATABASE="${ADE_QUALITY_DATABASE:-$ROOT/.ade/quality.db}"
mkdir -p "$ROOT/.ade"
"$PYTHON" "$ROOT/scripts/init_demo_evidence.py"
echo "Demo evidence initialized at $ADE_QUALITY_DATABASE"
