#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR - Python 3.11+ is required." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

PY="$ROOT/.venv/bin/python"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -e '.[dev]'
"$PY" -m pip install -e './hospitality-snowflake-data-platform[dev,parquet]'
"$PY" -m pip install -e './shiftforge[dev]'

if command -v npm >/dev/null 2>&1; then
  (cd local-data-harness && npm install --ignore-scripts)
else
  echo "WARN - npm is unavailable; the LDH quality step in the demo will not run."
fi

echo
echo "Demo environment ready."
echo "Run:"
echo "  source .venv/bin/activate"
echo "  make demo"
