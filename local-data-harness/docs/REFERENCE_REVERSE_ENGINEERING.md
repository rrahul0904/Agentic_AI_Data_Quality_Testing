# Reference reverse-engineering notes

Reference: https://github.com/AltimateAI/altimate-code

Observed public architecture:

- Bun/TypeScript monorepo.
- `packages/opencode` contains shipped core/server logic.
- TUI uses SolidJS + OpenTUI.
- Shared web UI lives in `packages/app`; desktop wraps it with Tauri.
- Local state uses SQLite.
- Model/provider layer is model-agnostic and includes Ollama/LM Studio.
- Data-engineering specialization is delivered through deterministic SQL/dbt/lineage/PII/FinOps/warehouse tooling.
- Agent modes scope permissions for Builder, Analyst, and Plan.

This repository is a clean-room draft of the architectural pattern, not a source-code copy.
