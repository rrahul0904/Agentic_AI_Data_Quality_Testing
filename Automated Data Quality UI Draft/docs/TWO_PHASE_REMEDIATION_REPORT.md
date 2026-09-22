# Two-phase stale-state remediation report

## Scope

This remediation uses the canonical application paths only:

- UI: `/Users/297159/Documents/Agentic_AI/Automated Data Quality UI Draft`
- Backend: `/Users/297159/Documents/Agentic_AI/Automated Data Quality Testing`
- Runtime: `/Users/297159/Documents/Agentic_AI/Automated Data Quality Testing/runtime/hospitality-data-reliability-lab`

No live provider, pipeline, warehouse, scheduler, or LLM operation was submitted.

## Phase 1 — scoped current state and safe preservation

Implemented:

- Current analysis and quality-plan reads are bound to the exact project, environment, and `source_table_scope_id`.
- UI proxy requests now forward the active source-table scope on overview, project-analysis, quality-plan, and current-run lookups.
- Scoped plan generation cannot use the newest analysis from another selected table.
- Missing or cleared scope fails closed instead of promoting a historical record to current state.
- Monitoring browser state is keyed by project/environment; legacy unscoped local-storage keys cannot restore a selection.
- Switching project/environment or removing/changing the active table clears current presentation state and invalidates analysis/plan scope.
- Historical runs remain available as historical records; they are not relabeled as current adapter state.
- Cleanup supports an explicit source-table scope and preserves ambiguous/unowned records as unresolved.
- The cleanup path does not touch connections, credentials, project identity, schemas, external data, DAGs, dbt code, or provider history.

## Phase 2 — verification and non-live release checks

Implemented and verified:

- Structured monitoring errors remain renderable and failed runs remain inspectable.
- Empty, unavailable, and failed states are distinct from persisted historical results.
- The browser release gate uses actual readiness and keyboard interaction rather than fixed settling sleeps for the monitored journey.
- The monitoring filter journey uses the current empty-state copy and validates that an explicit non-matching asset produces zero results.
- Test-only populated fixtures are isolated behind `ADQ_UI_TEST_FIXTURES=1` and the fixture scope; they are not used by normal project routes.

## Evidence

- Backend commits:
  - `8e3bc515754352d4bee40fece67a04feb6c7335a` — `fix scoped current-state reads and cleanup`.
  - `850c36958846092fb0d246215d5210ab63860e63` — `return zero incident counts for empty stores`.
- UI commit: `60d2054b9f2fceee14cea1e7b053e23fbb8b9523` — `docs: record two-phase remediation evidence`.
- Backend full suite: 712 passed, 1 existing Starlette deprecation warning.
- Backend targeted scope/cleanup/evidence suite: 23 passed, 1 existing Starlette deprecation warning.
- UI unit/regression suite: 41 passed.
- UI typecheck: passed with `npm run typecheck -- --incremental false`.
- UI production build: passed with `npm run build`.
- Browser/API checks: build coherence, API contracts, fixture checks, and the read-only release gate passed on the isolated production server at port 3040.

## Explicit limitation

The current project still has persisted historical records and the selected scope `postgres:public:booking_channels`. This remediation does not delete those records because their ownership is ambiguous and the request forbids destructive cleanup of uncertain data. To change the current view, use the normal scoped remove/clear selection flow or run the cleanup utility only after reviewing its dry-run manifest and explicitly approving the exact scope.

The active user worktrees also contain unrelated dirty/untracked files. They were preserved and are not part of this remediation commit.
