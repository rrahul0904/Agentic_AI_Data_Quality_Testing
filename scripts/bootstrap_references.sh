#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/references"
mkdir -p "$DEST"
repos=("mouryapt/databricks-agentic-ai-pipeline-poc" "kunumi/agentic-data-engineering" "tower/agentic-data-engineering" "NiclasOlofsson/dbt-core-mcp" "maseed260/data-migration-agent" "camharris93/sediment" "vaquarkhan/data-engineering-agent-skills" "rosettadb/dbt-studio" "AltimateAI/altimate-code")
for repo in "${repos[@]}"; do
  target="$DEST/${repo//\//__}"
  if [[ -d "$target/.git" ]]; then echo "[skip] $repo"; else echo "[clone] $repo"; git clone --depth 1 "https://github.com/$repo.git" "$target"; fi
done
