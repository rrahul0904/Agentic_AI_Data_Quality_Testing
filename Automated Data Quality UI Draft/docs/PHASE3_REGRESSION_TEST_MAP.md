# Phase 3 regression test map

Use this map to distinguish reproducible defects from preventive coverage. Passing fixture tests do not certify live connectors or the active server process.

| Flow / risk | Test or gate | Evidence expected | Current classification |
| --- | --- | --- | --- |
| Project/environment and active source scope | `tests/phase3-fixture-browser.test.ts`; `scripts/phase3-fixture-browser-gate.mjs`; `tests/catalog-coverage.test.ts` | Scope API distinguishes 15 available, 1 onboarded, 3 accepted fixture assets, 1 flow, 0 runtime observations; every browser URL is fixture scoped. | Preventive regression; live project is separately 15 available / 1 saved guest table. |
| Connections/readiness → onboarding → discovery | Phase 3 API contract gate and browser `/register-project` | Connector/readiness state, one selected source and one discovery source; no connector call from fixture mode. | Preventive regression. |
| Catalog → lineage → rules | Fixture API assertions + browser gate at 1280×720 and 1440×900 | Accepted fixture catalog, pipeline graph, quality plan/revision and rules render without client errors/overflow. | Preventive regression. |
| Run Jobs preview safety | Fixture action GET + `POST action=plan`, browser preview assertion | Exact one-step preview; no run is created; approval/execution controls remain disabled. | Preventive regression. |
| Monitoring/history and reconciliation history | Fixture GET contracts + rendered page checks | Persisted sample action state and historical baseline render; no comparison is submitted. | Preventive regression. |
| Ask AI rendering | Fixture GET + browser route | Scoped page loads; fixture responses are clearly test data. | Preventive regression; live provider behavior is covered by backend provider tests. |
| Responsive layout, keyboard, client exceptions | Existing fixture CDP gate | Visible focus, no horizontal overflow/out-of-view controls, no console errors at both desktop viewports. | Preventive regression. |
| Reload, cache, restart persistence | Manual operator checklist / service probes | Scope and persisted fixture/user state survive reload/restart without reseed. | Preventive test target; no destructive restart is performed in the fixture suite. |
| Connector recovery/privilege failures | Backend adapter test suites and manual diagnostics | Timeout is inconclusive; recovery reflects fresh metadata; privilege errors remain explicit. | Preventive test target. |
| Provider 400/429/timeout/wrong model/no key | `tests/test_action_agent_api.py`, `tests/test_operator_api.py` and provider regression cases | Safe status, no credential/payload leakage, configured model distinguished from verification. | Previously reproduced API/readiness defect; code regression covered, live restart verification remains separate. |
| dbt artifact/matching/reconciliation edge cases | Backend dbt/quality tests plus UI contract tests | Missing/stale manifest, ambiguity, partial scans, zero/null/duplicate/case/type mismatch represented honestly. | Preventive test target unless an issue-register row records reproduction. |
| Legacy plans, idempotency, worker restart | `tests/test_action_agent_api.py` and `tests/test_action_reconciler.py` | Invalid one-step end-to-end rejected at API; expired approval/duplicate submission/recovery cannot double-trigger. | Reproduced legacy-plan defect; API fix covered. Worker restart remains preventive coverage. |
| Large graph/catalog behavior | UI fixture generation/performance tests and manual checklist | Paging/virtualization and layout remain usable without freeze/overflow. | Preventive test target; not enterprise-scale certification. |

## Commands

From `Automated Data Quality UI Draft`:

```bash
npm test
npm run typecheck
node scripts/verify-phase4-fixtures.mjs
node scripts/phase3-fixture-browser-gate.mjs
```

From `Automated Data Quality Testing` (use the project venv when present):

```bash
.venv/bin/pytest -q tests/test_observability.py tests/test_action_agent_api.py
```

The browser gate uses a disposable Next server and headless Chrome profile, fixture-only API scope, and a separate Next build directory. It does not call an external provider, connector, or job executor. Live read-only smoke is an additional check and must not be conflated with this fixture gate.
