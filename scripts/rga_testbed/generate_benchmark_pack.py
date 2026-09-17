#!/usr/bin/env python3
"""Generate paired direct-SQL and Semantic View benchmark queries for RGA analytics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "benchmarks"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def build_queries(database: str) -> list[dict[str, str]]:
    mart = f"{database}.MART.REINSURANCE_PERFORMANCE"
    semantic = f"{database}.SEMANTIC.RGA_REINSURANCE_PERFORMANCE"
    return [
        {
            "id": "monthly_loss_ratio_by_cedant",
            "direct_sql": f"""select
    cedant_name,
    period_month,
    sum(ceded_claim_amount) / nullif(sum(ceded_premium), 0) as ceded_loss_ratio
from {mart}
group by 1, 2
order by 2, 1
""",
            "semantic_sql": f"""select *
from semantic_view(
  {semantic}
  metrics REINSURANCE_PERFORMANCE.CEDED_LOSS_RATIO
  dimensions REINSURANCE_PERFORMANCE.CEDANT_NAME, REINSURANCE_PERFORMANCE.PERIOD_MONTH
)
""",
        },
        {
            "id": "ceded_premium_by_treaty",
            "direct_sql": f"""select
    treaty_name,
    sum(ceded_premium) as total_ceded_premium
from {mart}
group by 1
order by 2 desc
""",
            "semantic_sql": f"""select *
from semantic_view(
  {semantic}
  metrics REINSURANCE_PERFORMANCE.TOTAL_CEDED_PREMIUM
  dimensions REINSURANCE_PERFORMANCE.TREATY_NAME
)
""",
        },
        {
            "id": "claims_and_exposure_by_month",
            "direct_sql": f"""select
    period_month,
    sum(ceded_claim_amount) as total_ceded_claims,
    sum(exposure_amount) as total_exposure,
    sum(claim_count) as total_claim_count
from {mart}
group by 1
order by 1
""",
            "semantic_sql": f"""select *
from semantic_view(
  {semantic}
  metrics REINSURANCE_PERFORMANCE.TOTAL_CEDED_CLAIMS,
          REINSURANCE_PERFORMANCE.TOTAL_EXPOSURE,
          REINSURANCE_PERFORMANCE.TOTAL_CLAIM_COUNT
  dimensions REINSURANCE_PERFORMANCE.PERIOD_MONTH
)
""",
        },
    ]


def generate(output: Path, database: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for query in build_queries(database):
        direct_path = output / f"{query['id']}.direct.sql"
        semantic_path = output / f"{query['id']}.semantic.sql"
        direct_path.write_text(query["direct_sql"].rstrip() + "\n", encoding="utf-8")
        semantic_path.write_text(query["semantic_sql"].rstrip() + "\n", encoding="utf-8")
        entries.append(
            {
                "id": query["id"],
                "direct_sql": direct_path.name,
                "semantic_sql": semantic_path.name,
            }
        )
    manifest = {
        "name": "rga_semantic_performance_benchmark",
        "database": database,
        "query_tag": "RGA_SEMANTIC_BENCHMARK",
        "queries": entries,
        "recommended_concurrency": [1, 5, 10, 25, 50],
        "measurements": ["elapsed_ms", "query_id", "rows", "bytes_scanned", "credits"],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    args = parse_args()
    manifest = generate(args.output, args.database)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
