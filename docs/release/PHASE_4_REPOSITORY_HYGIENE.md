# Phase 4 — Repository hygiene and clean-checkout certification

## Canonical repository boundary

This workspace contains two repositories that together make up the demo application:

- Root repository: the canonical UI in `Automated Data Quality UI Draft/`.
- Nested backend repository: `Automated Data Quality Testing/`, containing the API, workers, adapters, runtime scripts, migrations, and backend tests.

The demo launcher resolves both locations explicitly. A clean certification must validate the two repositories at their recorded revisions; it must not use the legacy `Automated Data Quality UI/` copy or any generated local runtime state.

## Tracked versus local-only material

Tracked release inputs are source code, tests, scripts, documentation, configuration templates, and deterministic fixtures. The following are deliberately excluded from version control:

- `.env` files, credentials, certificates, and private keys;
- `.ade/` databases and local runtime state;
- `node_modules/`, `.next/`, Python environments, caches, logs, and build output;
- generated screenshots and release reports under `artifacts/`;
- temporary review, recovery, and alternate-checkout directories.

The `.env.example` files remain tracked and are the only configuration templates used by clean-checkout setup.

## Reproducible validation

From the root checkout, validate the UI:

```bash
cd "Automated Data Quality UI Draft"
npm ci
npm test
npm run typecheck
npm run build
npm run verify:contracts
npm run verify:release
```

Validate the backend from its own clean checkout:

```bash
cd "Automated Data Quality Testing"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -c requirements-dev.lock -e '.[dev,testbed]'
python -m pip install -c requirements-dev.lock -e './hospitality-snowflake-data-platform[dev,parquet]'
PYTHONPATH=src python scripts/parse_dbt.py
PYTHONPATH=src pytest -q -p no:cacheprovider tests
```

The demo startup is intentionally separate from certification and does not seed or mutate provider data:

```bash
ADE_BUILD_UI=false ADE_SEED_DEMO_DATA=false ADE_START_MODE=demo ./scripts/demo-ui.sh
```

## Evidence classification

Repository tests and builds certify source reproducibility only. Adapter health, Airflow/dbt/Snowflake execution, hosted deployment behavior, and live OpenAI/provider behavior require environment-specific evidence and must not be inferred from this repository gate.
