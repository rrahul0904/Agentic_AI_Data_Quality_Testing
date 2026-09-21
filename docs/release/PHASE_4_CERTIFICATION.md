# Phase 4 certification record

Certification date: 2026-09-21

## Revisions

- Canonical UI source: `1d6d4c6602431006972d4d6717ced9b87e1a4af3`
- Root release documentation: `969daf0b97ff30217c044f33e3763111450eb09c`
- Canonical backend: `674ee499ce25a02a80ffbf5596c692396b310557`

The UI and backend are separate Git repositories. The backend repository has
no configured remote in this workspace, so its revision is committed locally
but not pushed.

## Repository-certified

### UI clean checkout

From a fresh local clone, using `package-lock.json`:

- `npm ci --no-audit --no-fund` — passed
- `npm run verify:fixtures` — passed: 3 catalog assets, 2 lineage links, 3 rule states, 3 monitoring states
- `npm test` — 21 passed
- `npm run typecheck` — passed
- `npm run build` — passed

The fixture is marked `TEST_ONLY_UI_STATE` and is not a production fallback.
It covers populated Catalog, Lineage, Rules, and Monitoring success/failure/
partial states with explicit project, environment, snapshot, plan, and run IDs.

### Backend clean checkout

From a fresh local clone, using the pinned constraints and declared extras:

- `pip install -c requirements-dev.lock -e '.[dev,testbed]' -e './hospitality-snowflake-data-platform[dev,parquet]'` — passed
- `python -m pip check` — passed
- `PYTHONPATH=src python scripts/parse_dbt.py` — passed and regenerated ignored dbt target artifacts
- `python -m ruff check src tests integration/e2e-tests` — passed
- `PYTHONPATH=src pytest -q -p no:cacheprovider tests` — 690 passed, 1 deprecation warning

The clean-checkout fix also makes repository discovery work when the checkout
itself is located below a directory named `backend`.

## Locally verified runtime

Against the running local demo (`127.0.0.1:3020` / `127.0.0.1:8011`):

- UI and API health responses — HTTP 200
- `npm run verify:contracts` — 6/6 passed, including exact run detail and project/environment scope
- `npm run verify:release` — passed: 28 route checks, 18 journey records, 13 screenshots, 0 console errors, 0 failures
- Browser coverage included 1280×720, 1366×768, 1440×900, 200% zoom, keyboard focus, blocked API recovery, empty states, and read-only planning controls

Generated screenshots and JSON reports remain ignored local evidence under
`Automated Data Quality UI Draft/artifacts/`.

## Environment-certified

Not established by this phase. The local runtime is reachable, but this record
does not certify a hosted deployment, external credentials, Snowflake network
policy, Airflow service, PostgreSQL service, dbt execution, or OpenAI provider.

## Not yet certified

- A live Airflow → Snowflake → dbt → quality → reconciliation workflow.
- Hosted deployment and multi-process worker behavior.
- External adapter authorization and provider execution evidence.
- A browser-rendered populated-state rehearsal using the committed fixture; the
  fixture contract is certified, while the live demo remains truthful to its
  current persisted state.
- A globally clean root worktree: unrelated legacy/alternate-console changes
  remain uncommitted and were intentionally excluded from the canonical UI
  commit.

This is repository and local-demo evidence, not a production-readiness claim.
