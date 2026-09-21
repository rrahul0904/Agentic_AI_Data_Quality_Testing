# Phase 4 implementation and verification report

Updated: 2026-09-21

This report is the evidence register for the canonical application only. The
legacy/alternate console changes in the root worktree were not staged or
modified by this work.

## Final status

**Repository implementation complete; environment verification pending.**

The canonical UI and backend source are tracked and reproducible from clean
checkouts. Local browser and backend verification pass. A hosted/provider
workflow has not been certified by this report.

## 1. Changes implemented

| Finding / requirement | Canonical implementation | Tests or evidence | Status |
| --- | --- | --- | --- |
| Monitoring history and remembered run details | Monitoring API/UI keeps explicit project/environment scope, preserves the selected run, renders structured errors as text, and never substitutes another run. | `verify:contracts`; browser journey for existing run → details; `tests/release-gate.test.ts` | FIXED + VERIFIED |
| Independent job planning | `/actions` resolves workspace on direct load and exposes operation, target, and exact-plan controls without requiring unrelated onboarding state. | `verify:contracts`; browser independent Airflow planning journey (read-only) | FIXED + VERIFIED |
| Canonical table identity and scope | Shared identity helpers and scoped API queries reject ambiguous/missing identities and preserve project/environment context. | UI unit tests; 690 backend tests; API contract runner | FIXED + VERIFIED |
| Responsive setup/connections/navigation | Container-aware action bars, responsive connection table layout, consistent page headings, task navigation, status semantics, visible keyboard focus, and overflow assertions. | Browser matrix at 1280, 1366, 1440, and 200% zoom | FIXED + VERIFIED |
| Populated UI coverage without fake runtime state | A `TEST_ONLY_UI_STATE` fixture is served only when an operator explicitly sets `ADQ_UI_TEST_FIXTURES=1` and requests the fixture project/environment. Production/default paths never use it. | Fixture validator; populated Catalog, Lineage, Rules, and run-detail browser journeys | FIXED + VERIFIED |
| Empty, loading, and error states | Normal scoped project routes remain empty when no current evidence exists; History and Schedules expose loading states; Monitoring has blocked-provider error and recovery journeys. | Browser release gate; `tests/release-gate.test.ts` | FIXED + VERIFIED |
| Browser gate quality | Release gate uses readiness polling, actual keyboard events, visible focus checks, overflow/control-overlap checks, exact run navigation, direct `/actions`, empty/error states, and populated fixture states. | `artifacts/phase3/release-gate-report.json`: 28 route checks, 18 journeys, 19 screenshots, 0 console errors | FIXED + VERIFIED |
| Clean-checkout reproducibility | Canonical source is tracked; generated artifacts, runtime stores, alternate worktrees, and local secrets are ignored. Backend discovery no longer rejects a checkout under a directory named `backend`; pinned dbt YAML parses. | Fresh UI and backend checkouts; clean backend status | FIXED + REPO VERIFIED |

## 2. Exact source revisions

- Canonical UI and Phase 4 source: `bfc8ce806a4abbf9c0d15212c21a261c1da48165`
- Clean-checkout certification documentation: `969daf0b97ff30217c044f33e3763111450eb09c`
- Previous root certification documentation HEAD: `09f927d30aaabebbe4f6d4d7fdf84b523eac6139`
- Backend clean-checkout fixes: `674ee499ce25a02a80ffbf5596c692396b310557`
- Root branch: `promote-snowflake-testbed`
- Root remote push: completed to `origin/promote-snowflake-testbed` at `09f927d30aaabebbe4f6d4d7fdf84b523eac6139`
- Backend nested repository: no configured remote; it cannot be pushed from this checkout.

## 3. Test evidence

| Check | Result |
| --- | --- |
| UI TypeScript | PASS — `npm run typecheck` |
| UI frontend tests | PASS — 21 tests |
| UI production build | PASS — `npm run build` on Next 15.5.24 |
| UI fixture validation | PASS — `npm run verify:fixtures` |
| UI API contracts | PASS — 6/6 read-only scope/detail checks |
| Browser journeys | PASS — `ADQ_UI_URL=http://127.0.0.1:3031 npm run verify:release` |
| Browser console errors | PASS — 0 |
| Backend lint | PASS — `ruff check src tests integration/e2e-tests` |
| Backend dbt parse | PASS — `PYTHONPATH=src python scripts/parse_dbt.py` |
| Backend tests | PASS — 690 tests, 1 deprecation warning |
| Dependency consistency | PASS — `pip check` |
| CI | Not run from this environment; no hosted CI run is being implied. |

The browser run used a production UI build on port 3031 with the existing
local backend on port 8011. The fixture server was explicitly started with
`ADQ_UI_TEST_FIXTURES=1`; fixture screenshots are test evidence, not live
execution evidence.

## 4. Browser matrix

All rows passed. Screenshot paths below are local generated artifacts under
`Automated Data Quality UI Draft/artifacts/phase3/` and are intentionally
ignored by Git.

| Route / journey | Viewports | State | Result | Evidence |
| --- | --- | --- | --- | --- |
| `/monitoring` | 1280×720, 1366×768, 1440×900, 200% | current scoped list | PASS | `*monitoring-monitoring.png` |
| `/monitoring` | 1280×720 | blocked API, then recovery | PASS | `1280x720-monitoring-error-monitoring.png`; report journey entries |
| `/monitoring` → selected run | all four | populated existing run and exact detail | PASS | report: `Project → Monitoring → existing run → run details` |
| `/actions` | all four | direct load and independent Airflow planning | PASS | `*run-jobs-actions.png`; report journey entry |
| `/register-project?phase=connections` | all four | connection actions and keyboard traversal | PASS | `*connections-register-project-phase-connections.png`; focus targets in report |
| `/objects-flows` | all four | current scoped empty state | PASS | `*catalog-objects-flows.png` |
| `/map-flows` | all four | current scoped empty state | PASS | `*lineage-map-flows.png` |
| `/test-plan?view=contracts` | all four | current scoped rules state | PASS | report route checks |
| `/objects-flows?fixture=phase4` | all four | populated Catalog fixture | PASS | `*fixture-catalog-objects-flows.png` |
| `/map-flows?fixture=phase4` | all four | populated Lineage fixture | PASS | `*fixture-lineage-map-flows.png` |
| `/test-plan?view=contracts&fixture=phase4` | all four | populated Rules fixture | PASS | `*fixture-rules-test-plan-view-contracts-mode-manage.png` |
| `/test-plan?view=execution&tab=history` | all four | persisted history state | PASS | `*history-test-plan-view-execution-mode-manage-tab-history.png` |

## 5. Repository state

- Canonical UI source files are tracked in the root repository.
- Canonical backend source, tests, scripts, and dbt project files are tracked
  in the nested backend repository.
- Nested backend repository status is clean.
- Root worktree is intentionally dirty with unrelated legacy/alternate-console
  edits and generated local files. They were not staged, changed, or presented
  as part of the canonical release:
  - alternate `apps/web` and `src/agentic_data_platform` work;
  - local benchmark/spec artifacts;
  - the root legacy launcher and README edits;
  - local TypeScript/build/runtime artifacts.
- `.gitignore` now excludes the alternate UI/backend worktrees, local runtime
  databases, recovery snapshots, benchmark results, generated artifacts, and
  fixture screenshots.

## 6. Remaining dependencies and limitations

### Repository defects

No known repository-level blocker remains for the implemented Phase 4 scope.

### Local-environment limitations

- The canonical browser gate was verified against the local runtime. A clean
  checkout was separately verified; a hosted deployment was not exercised.
- The nested backend has no remote configured, so its exact commit is locally
  verified but not pushed from this checkout.

### Credential/infrastructure dependencies

The following are not certified here: live Airflow → Snowflake → dbt → quality
→ reconciliation execution, multi-process worker recovery, production
authentication/authorization, corporate proxy/Zscaler behavior, Snowflake
network-policy authorization, and live OpenAI provider responses.

### Evidence boundary

The browser gate is read-only and does not approve or submit jobs. Passing
repository tests or local UI rendering does not prove external execution,
provider health, data correctness, or production capacity.

## 7. Required next phase

Run the hosted/provider certification workflow with a clean scoped project and
record the actual adapter health, Airflow run ID, dbt invocation and selected
nodes, Snowflake query/file evidence, quality result, reconciliation result,
monitoring persistence, and Ask AI citations. Keep any unavailable provider or
network-policy blocker explicit.
