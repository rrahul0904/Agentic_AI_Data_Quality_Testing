# Revenue Quality Certification — reference demo pipeline

This is the "Revenue Quality Certification" scenario from
`AGENTIC_AI_DATA_QUALITY_TECHNICAL_ARCHITECTURE_V2.md` §49 and the master
implementation prompt §36, built as a real, runnable dbt project.

## Pipeline

```
raw_orders (seed)
   -> stg_orders (staging)
   -> int_revenue (intermediate -- contains the injected defect)
   -> fact_revenue (mart)
```

## Business context

```
Net Revenue = gross amount - discount - refund
Cancelled orders must not contribute revenue.
COMPLETE and SHIPPED orders are recognized.
```

## The injected defect

`models/intermediate/int_revenue.sql` filters `WHERE status = 'COMPLETE'`.
The approved contract requires `WHERE status IN ('COMPLETE', 'SHIPPED')` --
this is deliberate, matching the spec's reference scenario exactly, so the
first certification run genuinely fails for the documented reason (not a
staged failure).

## Seed data (`seeds/raw_orders.csv`)

10 orders: 4 COMPLETE, 3 SHIPPED, 2 CANCELLED, 1 PENDING. With the defect
active, the 3 SHIPPED orders are silently dropped from `int_revenue`:

- Correct net revenue (COMPLETE + SHIPPED): **1015.00**
- Defective net revenue (COMPLETE only): **635.00**
- Difference: 380.00 (≈37% understatement)
- Row coverage: 3 recognized orders missing from `int_revenue`

## How to reproduce

1. Provision a local DuckDB dbt project via the ADE UI/API (`POST
   /api/dbt-projects`), then copy this directory's `seeds/` and `models/`
   into the provisioned project, replacing the `dbt init` starter content.
2. `dbt build` (or use the ADE "Run Whole Project" button).
3. Create the quality rules in `quality_rules.json` via `POST
   /api/quality-rules` (one call per rule) against the provisioned
   `dbt_project_id`.
4. Execute each rule (`POST /api/quality-rules/{id}/execute`) and evaluate
   certification (`POST /api/certifications/evaluate?dataset_ref=fact_revenue`)
   -- expect `FAILED`, naming the reconciliation/row-coverage rules.
5. Fix `int_revenue.sql` (`WHERE status IN ('COMPLETE', 'SHIPPED')`),
   re-run `dbt build`, re-execute the same rules, re-evaluate certification
   -- expect `CERTIFIED`.

`scripts/run_revenue_demo.py` in the backend automates steps 2-5 end to
end against a running ADE backend + provisioned project.
