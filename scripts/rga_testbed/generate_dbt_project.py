#!/usr/bin/env python3
"""Generate a dbt project for the RGA synthetic reinsurance domain."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "rga_domain.yml"
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "dbt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def build_project(config: dict[str, Any], output: Path) -> list[Path]:
    if output.exists():
        shutil.rmtree(output)
    written: list[Path] = []

    def emit(relative: str, content: str) -> None:
        path = output / relative
        _write(path, content)
        written.append(path)

    emit(
        "dbt_project.yml",
        """name: rga_reinsurance
version: 1.0.0
config-version: 2
profile: rga_reinsurance
model-paths: [models]
macro-paths: [macros]
clean-targets: [target, dbt_packages]
models:
  rga_reinsurance:
    staging:
      +materialized: view
      +schema: STAGING
    core:
      +materialized: table
      +schema: CORE
    marts:
      +materialized: table
      +schema: MART
""",
    )
    emit(
        "profiles.yml.example",
        """rga_reinsurance:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: "{{ env_var('SNOWFLAKE_ACCOUNT') }}"
      user: "{{ env_var('SNOWFLAKE_USER') }}"
      password: "{{ env_var('SNOWFLAKE_PASSWORD') }}"
      role: "{{ env_var('SNOWFLAKE_ROLE', 'SYSADMIN') }}"
      database: "{{ env_var('RGA_SNOWFLAKE_DATABASE', 'RGA_SYNTHETIC_TESTBED') }}"
      warehouse: "{{ env_var('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH') }}"
      schema: STAGING
      threads: 8
""",
    )
    emit(
        "macros/generate_schema_name.sql",
        """{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
""",
    )

    source_lines = [
        "version: 2",
        "sources:",
        "  - name: rga_raw",
        "    database: \"{{ env_var('RGA_SNOWFLAKE_DATABASE', 'RGA_SYNTHETIC_TESTBED') }}\"",
        "    schema: RAW",
        "    tables:",
    ]
    for entity, spec in config["entities"].items():
        source_lines += [
            f"      - name: {entity}",
            f"        identifier: {spec['target'].split('.', 1)[1]}",
            "        columns:",
            f"          - name: {spec['business_key']}",
            "            tests: [not_null, unique]",
        ]
    emit("models/sources/sources.yml", "\n".join(source_lines))

    for entity, spec in config["entities"].items():
        columns = list(spec["columns"])
        projection = ",\n    ".join(columns + ["_generation_id", "_source_file", "_ingested_at"])
        emit(
            f"models/staging/stg_{entity}.sql",
            f"""select
    {projection}
from {{{{ source('rga_raw', '{entity}') }}}}
""",
        )

    emit(
        "models/core/dim_cedant.sql",
        """{{ config(alias='DIM_CEDANT') }}
select
    cedant_id,
    cedant_name,
    country_code,
    currency_code,
    market_segment,
    active
from {{ ref('stg_cedants') }}
""",
    )
    emit(
        "models/core/dim_treaty.sql",
        """{{ config(alias='DIM_TREATY') }}
select
    t.treaty_id,
    t.cedant_id,
    c.cedant_name,
    t.treaty_name,
    t.treaty_type,
    t.effective_date,
    t.expiry_date,
    t.retention_amount,
    t.ceded_share_pct,
    t.currency_code,
    t.status
from {{ ref('stg_treaties') }} t
left join {{ ref('stg_cedants') }} c using (cedant_id)
""",
    )
    emit(
        "models/core/dim_policy.sql",
        """{{ config(alias='DIM_POLICY') }}
select
    p.policy_id,
    p.treaty_id,
    p.cedant_id,
    p.product_id,
    p.insured_id,
    p.issue_date,
    p.policy_status,
    p.sum_assured,
    p.annual_premium,
    p.currency_code,
    u.risk_class,
    u.decision as underwriting_decision,
    u.risk_score
from {{ ref('stg_policies') }} p
left join {{ ref('stg_underwriting_cases') }} u using (policy_id, insured_id)
""",
    )
    emit(
        "models/core/fct_premium.sql",
        """{{ config(alias='FCT_PREMIUM') }}
select
    premium_txn_id,
    policy_id,
    treaty_id,
    cedant_id,
    accounting_date,
    gross_premium,
    ceded_premium,
    currency_code
from {{ ref('stg_premiums') }}
""",
    )
    emit(
        "models/core/fct_claim.sql",
        """{{ config(alias='FCT_CLAIM') }}
select
    claim_id,
    policy_id,
    treaty_id,
    insured_id,
    event_date,
    reported_date,
    claim_status,
    cause_code,
    claim_amount,
    ceded_claim_amount,
    currency_code
from {{ ref('stg_claims') }}
""",
    )
    emit(
        "models/core/fct_exposure.sql",
        """{{ config(alias='FCT_EXPOSURE') }}
select
    exposure_id,
    policy_id,
    treaty_id,
    cedant_id,
    exposure_month,
    exposed_amount,
    exposure_fraction,
    currency_code
from {{ ref('stg_exposure_monthly') }}
""",
    )
    emit(
        "models/marts/mart_reinsurance_performance.sql",
        """{{ config(alias='REINSURANCE_PERFORMANCE') }}
with premium_monthly as (
    select
        cedant_id,
        treaty_id,
        date_trunc('month', accounting_date)::date as period_month,
        sum(gross_premium) as gross_premium,
        sum(ceded_premium) as ceded_premium,
        count(*) as premium_transaction_count
    from {{ ref('fct_premium') }}
    group by 1, 2, 3
),
claim_monthly as (
    select
        p.cedant_id,
        c.treaty_id,
        date_trunc('month', c.event_date)::date as period_month,
        sum(c.claim_amount) as gross_claim_amount,
        sum(c.ceded_claim_amount) as ceded_claim_amount,
        count(*) as claim_count
    from {{ ref('fct_claim') }} c
    join {{ ref('dim_policy') }} p using (policy_id)
    group by 1, 2, 3
),
exposure_monthly as (
    select
        cedant_id,
        treaty_id,
        exposure_month as period_month,
        sum(exposed_amount * exposure_fraction) as exposure_amount,
        count(distinct policy_id) as exposed_policy_count
    from {{ ref('fct_exposure') }}
    group by 1, 2, 3
),
keys as (
    select cedant_id, treaty_id, period_month from premium_monthly
    union
    select cedant_id, treaty_id, period_month from claim_monthly
    union
    select cedant_id, treaty_id, period_month from exposure_monthly
)
select
    k.cedant_id,
    d.cedant_name,
    k.treaty_id,
    d.treaty_name,
    d.treaty_type,
    k.period_month,
    coalesce(p.gross_premium, 0) as gross_premium,
    coalesce(p.ceded_premium, 0) as ceded_premium,
    coalesce(c.gross_claim_amount, 0) as gross_claim_amount,
    coalesce(c.ceded_claim_amount, 0) as ceded_claim_amount,
    coalesce(e.exposure_amount, 0) as exposure_amount,
    coalesce(p.premium_transaction_count, 0) as premium_transaction_count,
    coalesce(c.claim_count, 0) as claim_count,
    coalesce(e.exposed_policy_count, 0) as exposed_policy_count,
    coalesce(c.ceded_claim_amount, 0) / nullif(coalesce(p.ceded_premium, 0), 0) as ceded_loss_ratio,
    coalesce(p.ceded_premium, 0) / nullif(coalesce(p.gross_premium, 0), 0) as ceded_premium_rate
from keys k
left join premium_monthly p using (cedant_id, treaty_id, period_month)
left join claim_monthly c using (cedant_id, treaty_id, period_month)
left join exposure_monthly e using (cedant_id, treaty_id, period_month)
left join {{ ref('dim_treaty') }} d using (cedant_id, treaty_id)
""",
    )

    emit(
        "models/schema.yml",
        """version: 2
models:
  - name: dim_cedant
    columns:
      - name: cedant_id
        tests: [not_null, unique]
  - name: dim_treaty
    columns:
      - name: treaty_id
        tests: [not_null, unique]
  - name: dim_policy
    columns:
      - name: policy_id
        tests: [not_null, unique]
  - name: fct_premium
    columns:
      - name: premium_txn_id
        tests: [not_null, unique]
  - name: fct_claim
    columns:
      - name: claim_id
        tests: [not_null, unique]
  - name: fct_exposure
    columns:
      - name: exposure_id
        tests: [not_null, unique]
  - name: mart_reinsurance_performance
    columns:
      - name: cedant_id
        tests: [not_null]
      - name: treaty_id
        tests: [not_null]
      - name: period_month
        tests: [not_null]
""",
    )
    return written


def main() -> int:
    args = parse_args()
    files = build_project(load_config(args.config), args.output)
    print(f"generated {len(files)} dbt files under {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
