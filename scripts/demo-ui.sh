#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then PYTHON="$(command -v python3)"; fi
if ! command -v npm >/dev/null 2>&1; then echo "ERROR - npm is required for the operator console." >&2; exit 1; fi

export PYTHONPATH="$ROOT/src"
export ADE_DEMO_MODE="${ADE_DEMO_MODE:-true}"
export ADE_DEMO_PROJECT="${ADE_DEMO_PROJECT:-$ROOT/hospitality-snowflake-data-platform}"
export ADE_QUALITY_DATABASE="${ADE_QUALITY_DATABASE:-$ROOT/.ade/quality.db}"
export ADE_DATABASE_PATH="${ADE_DATABASE_PATH:-$ROOT/.ade/control-plane.db}"
export ADE_UI_ORIGINS="${ADE_UI_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"
"$ROOT/scripts/init-demo-data.sh" >/dev/null

cleanup() {
  trap - INT TERM EXIT
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting Agentic Data Engineering OS — Demo v0.4"
echo "  API:      http://127.0.0.1:8001"
echo "  Console:  http://127.0.0.1:3000"
echo "  Mode:     LOCAL SIMULATION"
echo "Snowflake live: SKIP unless credentials are configured."
echo "Oracle live:    SKIP in demo mode."
echo "Docker:         not required."

"$PYTHON" -m uvicorn agentic_data_platform.api.app:app --host 127.0.0.1 --port 8001 &
API_PID=$!
(
  cd "$ROOT/apps/web"
  NEXT_PUBLIC_ADE_API_URL="http://127.0.0.1:8001" npm run dev -- --hostname 127.0.0.1 --port 3000
) &
WEB_PID=$!

for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:8001/api/v1/overview" >/dev/null 2>&1 && curl -fsS "http://127.0.0.1:3000" >/dev/null 2>&1; then
    echo
    echo "Demo is ready: http://127.0.0.1:3000"
    echo "Press Ctrl+C to stop both services."
    wait "$API_PID" "$WEB_PID"
    exit $?
  fi
  if ! kill -0 "$API_PID" 2>/dev/null || ! kill -0 "$WEB_PID" 2>/dev/null; then
    echo "ERROR - a demo service exited before becoming ready." >&2
    wait "$API_PID" "$WEB_PID" || true
    exit 1
  fi
  sleep 0.5
done
echo "ERROR - demo services did not become ready." >&2
exit 1
