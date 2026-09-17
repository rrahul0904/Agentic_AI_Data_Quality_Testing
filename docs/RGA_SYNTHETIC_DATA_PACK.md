# RGA-style Synthetic Data Pack

This domain pack extends the existing hospitality Snowflake testbed without changing the hospitality generator.
It creates **synthetic Life & Health reinsurance test data only**; it is not based on proprietary RGA data and contains no real PII.

## Scope

The first vertical slice models:

- cedants
- reinsurance treaties
- insurance products
- insured lives
- policies and coverages
- underwriting cases
- gross and ceded premiums
- claims, claim payments, and reserves
- monthly exposure

The same YAML contract drives both the data generator and Snowflake RAW DDL so data and table definitions cannot silently drift.

## Quick start

```bash
python scripts/rga_testbed/generate_data.py --preset tiny --seed 42
python scripts/rga_testbed/validate_dataset.py --input artifacts/rga_testbed
python scripts/rga_testbed/generate_snowflake_ddl.py
```

For a bounded developer run that overrides only policy volume:

```bash
python scripts/rga_testbed/generate_data.py --preset tiny --policies 10000 --seed 42
```

## Scale presets

| Preset | Policies | Intended use |
| --- | ---: | --- |
| tiny | 500 | unit/integration tests |
| small | 50,000 | local functional tests |
| medium | 1,000,000 | warehouse performance tests |
| large | 10,000,000 | large-scale Snowflake benchmark |
| stress | 100,000,000 | distributed generation / stress target |

Monthly exposure can produce roughly 12x the active-policy volume, so the `stress` preset is a target profile and should be generated with distributed or partitioned execution rather than a single laptop process.

## Business invariants

The generator enforces or derives:

- every policy belongs to a valid cedant and treaty;
- every policy references a synthetic insured life and product;
- premiums are positive and ceded premium is treaty-share based;
- claims occur after policy issue;
- claim report dates are on or after event dates;
- ceded claim amounts do not exceed gross claim amounts;
- paid claims create payment rows;
- open claims create reserve rows;
- active policies create monthly exposure rows.

## Snowflake objects

`generate_snowflake_ddl.py` creates:

- `RGA_SYNTHETIC_TESTBED` database by default;
- `RAW`, `STAGING`, `CORE`, `MART`, and `AUDIT` schemas;
- CSV file format and internal stage;
- one RAW table for each domain entity;
- audit manifest table for generation metadata.

The next slices should add Airflow ingestion metadata, dbt STAGING/CORE/MART models, CDC/failure fixtures, and Semantic View benchmark models for Power BI, Excel, Snowflake SQL, and AI.
