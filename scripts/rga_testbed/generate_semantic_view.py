#!/usr/bin/env python3
"""Generate a native Snowflake Semantic View YAML and verify/deploy SQL for RGA analytics."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "semantic"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def build_semantic_spec(database: str) -> dict:
    return {
        "name": "RGA_REINSURANCE_PERFORMANCE",
        "description": "Governed synthetic Life & Health reinsurance performance metrics for BI, Excel and AI evaluation.",
        "tables": [
            {
                "name": "REINSURANCE_PERFORMANCE",
                "description": "Monthly cedant and treaty performance at cedant+treaty+month grain.",
                "base_table": {"database": database, "schema": "MART", "table": "REINSURANCE_PERFORMANCE"},
                "primary_key": {"columns": ["CEDANT_ID", "TREATY_ID", "PERIOD_MONTH"]},
                "dimensions": [
                    {
                        "name": "CEDANT_ID",
                        "synonyms": ["client id", "ceding company id"],
                        "description": "Synthetic cedant identifier.",
                        "expr": "CEDANT_ID",
                        "data_type": "VARCHAR",
                    },
                    {
                        "name": "CEDANT_NAME",
                        "synonyms": ["client", "ceding company", "cedant"],
                        "description": "Synthetic cedant name.",
                        "expr": "CEDANT_NAME",
                        "data_type": "VARCHAR",
                    },
                    {
                        "name": "TREATY_ID",
                        "synonyms": ["reinsurance treaty id"],
                        "description": "Synthetic treaty identifier.",
                        "expr": "TREATY_ID",
                        "data_type": "VARCHAR",
                    },
                    {
                        "name": "TREATY_NAME",
                        "synonyms": ["reinsurance treaty"],
                        "description": "Synthetic treaty name.",
                        "expr": "TREATY_NAME",
                        "data_type": "VARCHAR",
                    },
                    {
                        "name": "TREATY_TYPE",
                        "synonyms": ["reinsurance type"],
                        "description": "Treaty structure such as YRT, coinsurance, MODCO or excess of loss.",
                        "expr": "TREATY_TYPE",
                        "data_type": "VARCHAR",
                    },
                ],
                "time_dimensions": [
                    {
                        "name": "PERIOD_MONTH",
                        "synonyms": ["month", "reporting month", "valuation month"],
                        "description": "Calendar month for aggregated performance.",
                        "expr": "PERIOD_MONTH",
                        "data_type": "DATE",
                    }
                ],
                "facts": [
                    {"name": "GROSS_PREMIUM", "expr": "GROSS_PREMIUM", "data_type": "NUMBER(38,2)"},
                    {"name": "CEDED_PREMIUM", "expr": "CEDED_PREMIUM", "data_type": "NUMBER(38,2)"},
                    {"name": "GROSS_CLAIM_AMOUNT", "expr": "GROSS_CLAIM_AMOUNT", "data_type": "NUMBER(38,2)"},
                    {"name": "CEDED_CLAIM_AMOUNT", "expr": "CEDED_CLAIM_AMOUNT", "data_type": "NUMBER(38,2)"},
                    {"name": "EXPOSURE_AMOUNT", "expr": "EXPOSURE_AMOUNT", "data_type": "NUMBER(38,2)"},
                    {"name": "CLAIM_COUNT", "expr": "CLAIM_COUNT", "data_type": "NUMBER"},
                    {"name": "EXPOSED_POLICY_COUNT", "expr": "EXPOSED_POLICY_COUNT", "data_type": "NUMBER"},
                ],
                "metrics": [
                    {
                        "name": "TOTAL_GROSS_PREMIUM",
                        "synonyms": ["gross premium"],
                        "description": "Total gross premium before reinsurance cession.",
                        "expr": "SUM(GROSS_PREMIUM)",
                    },
                    {
                        "name": "TOTAL_CEDED_PREMIUM",
                        "synonyms": ["ceded premium", "reinsurance premium"],
                        "description": "Total premium ceded to the reinsurer.",
                        "expr": "SUM(CEDED_PREMIUM)",
                    },
                    {
                        "name": "TOTAL_GROSS_CLAIMS",
                        "synonyms": ["gross claims"],
                        "description": "Total gross claim amount.",
                        "expr": "SUM(GROSS_CLAIM_AMOUNT)",
                    },
                    {
                        "name": "TOTAL_CEDED_CLAIMS",
                        "synonyms": ["ceded claims", "reinsurance claims"],
                        "description": "Total claim amount ceded under the treaty.",
                        "expr": "SUM(CEDED_CLAIM_AMOUNT)",
                    },
                    {
                        "name": "TOTAL_EXPOSURE",
                        "synonyms": ["exposure", "amount at risk"],
                        "description": "Exposure amount weighted by exposure fraction.",
                        "expr": "SUM(EXPOSURE_AMOUNT)",
                    },
                    {
                        "name": "TOTAL_CLAIM_COUNT",
                        "synonyms": ["claims", "number of claims"],
                        "description": "Count of claims represented in the monthly mart.",
                        "expr": "SUM(CLAIM_COUNT)",
                    },
                    {
                        "name": "CEDED_LOSS_RATIO",
                        "synonyms": ["loss ratio", "reinsurance loss ratio"],
                        "description": "Ceded claims divided by ceded premium at the selected aggregation grain.",
                        "expr": "SUM(CEDED_CLAIM_AMOUNT) / NULLIF(SUM(CEDED_PREMIUM), 0)",
                    },
                    {
                        "name": "CEDED_PREMIUM_RATE",
                        "synonyms": ["ceded rate", "cession rate"],
                        "description": "Ceded premium divided by gross premium.",
                        "expr": "SUM(CEDED_PREMIUM) / NULLIF(SUM(GROSS_PREMIUM), 0)",
                    },
                ],
            }
        ],
        "verified_queries": [
            {
                "name": "monthly_ceded_loss_ratio_by_cedant",
                "question": "What is the monthly ceded loss ratio by cedant?",
                "sql": (
                    f"SELECT * FROM SEMANTIC_VIEW({database}.SEMANTIC.RGA_REINSURANCE_PERFORMANCE "
                    "METRICS REINSURANCE_PERFORMANCE.CEDED_LOSS_RATIO "
                    "DIMENSIONS REINSURANCE_PERFORMANCE.CEDANT_NAME, REINSURANCE_PERFORMANCE.PERIOD_MONTH)"
                ),
                "use_as_onboarding_question": True,
            }
        ],
    }


def render_sql(database: str, yaml_text: str, verify_only: bool) -> str:
    verify = "TRUE" if verify_only else "FALSE"
    return (
        "CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(\n"
        f"  '{database}.SEMANTIC',\n"
        "  $$\n"
        f"{yaml_text.rstrip()}\n"
        "  $$,\n"
        f"  {verify},\n"
        "  TRUE\n"
        ");\n"
    )


def generate(output: Path, database: str) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    spec = build_semantic_spec(database)
    yaml_text = yaml.safe_dump(spec, sort_keys=False, width=120)
    files = [
        (output / "rga_reinsurance_performance.yml", yaml_text),
        (output / "verify_semantic_view.sql", render_sql(database, yaml_text, True)),
        (output / "deploy_semantic_view.sql", render_sql(database, yaml_text, False)),
    ]
    for path, content in files:
        path.write_text(content, encoding="utf-8")
    return [path for path, _ in files]


def main() -> int:
    args = parse_args()
    files = generate(args.output, args.database)
    for path in files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
