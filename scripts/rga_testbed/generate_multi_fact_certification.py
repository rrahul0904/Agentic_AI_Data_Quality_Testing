#!/usr/bin/env python3
"""Generate a safe multi-fact query-plan reference for RGA premium, claim, and exposure analytics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "multi_fact"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def build_plan() -> dict:
    shared_grain = ["CEDANT_ID", "TREATY_ID", "PERIOD_MONTH"]
    return {
        "name": "rga_multi_fact_safe_aggregation",
        "shared_grain": shared_grain,
        "facts": [
            {
                "name": "premium",
                "source": "CORE.FCT_PREMIUM",
                "time_expression": "DATE_TRUNC('month', ACCOUNTING_DATE)::DATE",
                "measures": {
                    "GROSS_PREMIUM": "SUM(GROSS_PREMIUM)",
                    "CEDED_PREMIUM": "SUM(CEDED_PREMIUM)",
                },
            },
            {
                "name": "claim",
                "source": "CORE.FCT_CLAIM",
                "requires_dimension_bridge": "CORE.DIM_POLICY",
                "time_expression": "DATE_TRUNC('month', EVENT_DATE)::DATE",
                "measures": {
                    "GROSS_CLAIM_AMOUNT": "SUM(CLAIM_AMOUNT)",
                    "CEDED_CLAIM_AMOUNT": "SUM(CEDED_CLAIM_AMOUNT)",
                    "CLAIM_COUNT": "COUNT(*)",
                },
            },
            {
                "name": "exposure",
                "source": "CORE.FCT_EXPOSURE",
                "time_expression": "EXPOSURE_MONTH",
                "measures": {
                    "EXPOSURE_AMOUNT": "SUM(EXPOSED_AMOUNT * EXPOSURE_FRACTION)",
                    "EXPOSED_POLICY_COUNT": "COUNT(DISTINCT POLICY_ID)",
                },
            },
        ],
        "planning_rules": [
            "aggregate_each_fact_to_shared_grain_before_join",
            "build_union_of_shared_keys",
            "join_only_aggregated_fact_results",
            "compute_cross_fact_ratios_after_safe_join",
            "never_join_raw_fact_tables_directly",
        ],
        "derived_metrics": {
            "CEDED_LOSS_RATIO": "CEDED_CLAIM_AMOUNT / NULLIF(CEDED_PREMIUM, 0)",
            "CEDED_PREMIUM_RATE": "CEDED_PREMIUM / NULLIF(GROSS_PREMIUM, 0)",
        },
    }


def render_reference_sql() -> str:
    return """with premium_monthly as (
    select
        cedant_id,
        treaty_id,
        date_trunc('month', accounting_date)::date as period_month,
        sum(gross_premium) as gross_premium,
        sum(ceded_premium) as ceded_premium
    from RGA_SYNTHETIC_TESTBED.CORE.FCT_PREMIUM
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
    from RGA_SYNTHETIC_TESTBED.CORE.FCT_CLAIM c
    join RGA_SYNTHETIC_TESTBED.CORE.DIM_POLICY p using (policy_id)
    group by 1, 2, 3
),
exposure_monthly as (
    select
        cedant_id,
        treaty_id,
        exposure_month as period_month,
        sum(exposed_amount * exposure_fraction) as exposure_amount,
        count(distinct policy_id) as exposed_policy_count
    from RGA_SYNTHETIC_TESTBED.CORE.FCT_EXPOSURE
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
    k.treaty_id,
    k.period_month,
    coalesce(p.gross_premium, 0) as gross_premium,
    coalesce(p.ceded_premium, 0) as ceded_premium,
    coalesce(c.gross_claim_amount, 0) as gross_claim_amount,
    coalesce(c.ceded_claim_amount, 0) as ceded_claim_amount,
    coalesce(e.exposure_amount, 0) as exposure_amount,
    coalesce(c.claim_count, 0) as claim_count,
    coalesce(e.exposed_policy_count, 0) as exposed_policy_count,
    coalesce(c.ceded_claim_amount, 0) / nullif(coalesce(p.ceded_premium, 0), 0) as ceded_loss_ratio
from keys k
left join premium_monthly p using (cedant_id, treaty_id, period_month)
left join claim_monthly c using (cedant_id, treaty_id, period_month)
left join exposure_monthly e using (cedant_id, treaty_id, period_month);
"""


def generate(output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "multi_fact_plan.json"
    sql_path = output / "multi_fact_reference.sql"
    plan_path.write_text(json.dumps(build_plan(), indent=2) + "\n", encoding="utf-8")
    sql_path.write_text(render_reference_sql(), encoding="utf-8")
    return [plan_path, sql_path]


def main() -> int:
    args = parse_args()
    files = generate(args.output)
    print(json.dumps({"status": "PASS", "files": [str(path) for path in files]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
