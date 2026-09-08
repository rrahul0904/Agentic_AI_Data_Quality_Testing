# Airflow Capability Ledger

Modern target: **Airflow 3.x semantics**, with static compatibility for relevant Airflow 2.x projects.

- DONE: **82**
- PARTIAL: **0**
- MISSING: **0**
- SKIP_EXTERNAL: **15**
- NOT_APPLICABLE: **0**

Static DAG intelligence is dependency-free and never imports user DAG modules. Live Airflow/API/cloud operations are implemented behind version-aware adapters and ToolRegistry governance; they remain `SKIP_EXTERNAL` only where credentials/services are unavailable.
