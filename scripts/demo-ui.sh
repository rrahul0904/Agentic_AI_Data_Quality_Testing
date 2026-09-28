#!/usr/bin/env bash
set -euo pipefail

# Deprecated compatibility entrypoint. The active application lives in the
# backend project and uses the Draft UI on ports 8011/3020.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CANONICAL="$ROOT/Automated Data Quality Testing/scripts/demo-ui.sh"

if [[ ! -x "$CANONICAL" ]]; then
  echo "ERROR - canonical launcher not found: $CANONICAL" >&2
  exit 1
fi

echo "DEPRECATED: this launcher no longer starts the legacy apps/web console." >&2
echo "Redirecting to: $CANONICAL" >&2
exec "$CANONICAL" "$@"
