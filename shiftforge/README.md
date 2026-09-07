# ShiftForge

A local-first, compile-aware **BigQuery → Redshift dbt migration agent** reconstructed from the supplied converter-agent demo and hardened for real repositories.

## What it does

- discovers dbt SQL models;
- applies deterministic BigQuery→Redshift compatibility rules;
- detects high-risk constructs that require semantic review;
- verifies Redshift sort keys are actually produced by the SELECT list;
- accepts explicit source-expression hints instead of hallucinating missing columns;
- writes into a separate output tree only after `--approve`;
- can run `dbt compile` in a temporary cloned project so source models are never renamed/deleted;
- emits JSON and Markdown conversion reports;
- exposes both a CLI and a web/API MVP.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q

# Dry-run a repository
shiftforge convert examples/revinate --hints examples/hints.json

# Write converted models
shiftforge convert examples/revinate \
  --hints examples/hints.json \
  --output /tmp/revinate-redshift \
  --approve

# Web review UI
uvicorn shiftforge.api:app --reload --port 8080
```

Open `http://localhost:8080`.

## Example sort-key invariant

If a model config declares:

```sql
{{ config(sort=['account_country']) }}
```

but the model does not output `account_country`, ShiftForge blocks the model. Give an explicit hint:

```json
{
  "models/account_hierarchy.sql": {
    "account_country": "sfdc_account.BillingCountry"
  }
}
```

The converter then adds the projected alias and records the transformation as `RS_SORTKEY_001`.

## Current rule coverage

MVP deterministic rules include backtick identifiers, `IFNULL`, `COUNTIF`, simple `STRING_AGG`, `DATE_ADD`, `REGEXP_CONTAINS`, and `SAFE_CAST` normalization. Array/STRUCT/JSON/geospatial cases are intentionally flagged for review rather than silently rewritten.

See `docs/REVERSE_ENGINEERING.md`, `docs/ARCHITECTURE.md`, and `docs/LAUNCH_PLAN.md`.
