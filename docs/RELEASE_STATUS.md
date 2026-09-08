# Release Status

This document records the current engineering state of **Agentic Data Engineering OS**.

## Status vocabulary

- **IMPLEMENTED** — production code exists in the repository.
- **LOCAL_VERIFIED** — deterministic/local tests or demos verify the path.
- **LIVE_VERIFIED** — a real external service was exercised successfully.
- **SKIP_EXTERNAL** — implementation exists, but required external credentials/services are unavailable.
- **NOT_RUN_EXTERNAL** — an external certification harness exists but has not yet been executed.
- **FAIL** — a verification path currently fails.

## Current engineering state

The major product subsystems are implemented: discovery, SQL, dbt, Airflow, lineage, data quality, reconciliation, Data Diff, agentic investigation, Git review automation, providers, MCP, skills, training, sessions/replay, FinOps, governance, migration, web, TUI, CLI and API.

The repository should only be called release-certified after the newest exact `main` SHA completes the required CI cycle.

## Capability status

| Capability | Implementation state | Verification boundary |
| --- | --- | --- |
| Repository discovery | IMPLEMENTED | Local/CI |
| SQL intelligence | IMPLEMENTED | Local/CI; live query evidence optional |
| dbt engineering | IMPLEMENTED | Local/CI; warehouse required for live execution |
| Airflow engineering | IMPLEMENTED | Static/local/CI; live runtime requires Airflow service |
| Cross-system lineage | IMPLEMENTED | Local/CI |
| Data quality | IMPLEMENTED | Local/CI |
| Reconciliation | IMPLEMENTED | Local/CI |
| Data Diff default local suite | IMPLEMENTED | Local benchmark through configured default sizes |
| 100M+ Data Diff | HARNESS IMPLEMENTED | NOT_RUN_EXTERNAL until qualifying external run succeeds |
| Agentic investigation | IMPLEMENTED | Local deterministic/E2E |
| GitHub review | IMPLEMENTED | Local/contract; live delivery needs token/PR |
| GitLab review | IMPLEMENTED | Local/contract; live delivery needs token/MR |
| Providers | IMPLEMENTED | Contract/local; live provider needs credentials/server |
| MCP | IMPLEMENTED | Local/contract; external server varies |
| Skills | IMPLEMENTED | Local/CI |
| Training | IMPLEMENTED | Local/CI |
| Sessions/replay | IMPLEMENTED | Local/CI |
| FinOps | IMPLEMENTED | Local engine; live warehouse required for real costs |
| Governance | IMPLEMENTED | Local engine; live warehouse required for deep grants/access |
| Migration | IMPLEMENTED | Local/CI |
| Web console | IMPLEMENTED | Typecheck/build/smoke |
| Textual TUI | IMPLEMENTED | Local/CI |
| CLI | IMPLEMENTED | Local/fresh-clone CI |
| FastAPI | IMPLEMENTED | Local/API/integration CI |

## External certification boundary

Real credentials or infrastructure are needed for live Snowflake, Oracle, PostgreSQL/Redshift, BigQuery, Databricks, cloud Airflow, hosted LLMs, GitHub PR delivery, GitLab MR delivery, production FinOps/RBAC evidence and 100M+ cross-warehouse Data Diff.

Unavailable external systems must remain explicit `SKIP_EXTERNAL`, `BLOCKED_EXTERNAL` or `NOT_RUN_EXTERNAL` states rather than being converted to PASS.

## Canonical verification

```bash
make verify
```

Additional external/live harnesses are available through the dedicated Makefile targets and GitHub Actions workflows.

The final release verdict must always refer to the newest exact `main` SHA, not an earlier green commit.
