#!/usr/bin/env python3
"""Generate Snowflake acceleration candidates from the canonical semantic contract."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, semantic_view_fqn
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, semantic_view_fqn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "acceleration"

_SIMPLE_ADDITIVE = re.compile(r"^\s*(SUM|COUNT|MIN|MAX)\s*\(", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def _metric_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in contract["metrics"]}


def _is_reaggregatable(metric: dict[str, Any]) -> bool:
    expression = metric["expr"].upper()
    return bool(_SIMPLE_ADDITIVE.match(expression)) and "/" not in expression and "DISTINCT" not in expression


def _materialization_name(query_id: str) -> str:
    safe = re.sub(r"[^A-Z0-9]+", "_", query_id.upper()).strip("_")
    return f"MAT_{safe}"[:255]


def build_plan(database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = load_semantic_contract(contract_path, database)
    table = contract["table_alias"]
    metrics = _metric_map(contract)
    semantic_cfg = contract["acceleration"]["semantic_sql"]
    candidates = []

    for query in contract["verified_queries"]:
        query_metrics = [metrics[name] for name in query["metrics"]]
        reaggregatable = all(_is_reaggregatable(metric) for metric in query_metrics)
        candidates.append(
            {
                "name": _materialization_name(query["id"]),
                "query_id": query["id"],
                "question": query["question"],
                "dimensions": query.get("dimensions", []),
                "metrics": query["metrics"],
                "reaggregatable": reaggregatable,
                "coverage": "rollup_eligible" if reaggregatable else "exact_or_more_restrictive_grain",
                "refresh_mode": semantic_cfg["refresh_mode"],
            }
        )

    return {
        "semantic_view": semantic_view_fqn(contract),
        "max_staleness_sec": int(semantic_cfg["max_staleness_sec"]),
        "warehouse_env": semantic_cfg["warehouse_env"],
        "semantic_sql": {
            "materializations": candidates,
            "note": (
                "These candidates accelerate Semantic SQL when Snowflake can rewrite the query to a covering materialization. "
                "Derived/non-additive metrics are marked as non-reaggregatable."
            ),
        },
        "ai_physical_sql": {
            **contract["acceleration"]["ai_physical_sql"],
            "telemetry_rules": [
                {
                    "signal": "queued_overload_time > 0",
                    "candidate": "warehouse_concurrency_or_multi_cluster",
                },
                {
                    "signal": "bytes_spilled_to_remote_storage > 0",
                    "candidate": "larger_warehouse_or_query_shape_reduction",
                },
                {
                    "signal": "high_bytes_scanned_repeated_query_shape",
                    "candidate": "dynamic_table_or_aggregate_table",
                },
                {
                    "signal": "high_selectivity_predicates_on_large_tables",
                    "candidate": "search_optimization_or_clustering",
                },
            ],
        },
    }


def render_materialization_sql(plan: dict[str, Any]) -> str:
    view = plan["semantic_view"]
    lines = [
        "-- Generated acceleration candidates. Review benchmark evidence before live execution.",
        f"ALTER SEMANTIC VIEW {view} SET MAX_STALENESS = {plan['max_staleness_sec']};",
        "",
    ]
    for item in plan["semantic_sql"]["materializations"]:
        dimensions = ", ".join(f"REINSURANCE_PERFORMANCE.{name}" for name in item["dimensions"])
        metrics = ", ".join(f"REINSURANCE_PERFORMANCE.{name}" for name in item["metrics"])
        lines.extend(
            [
                f"-- {item['query_id']}: {item['question']}",
                f"-- coverage={item['coverage']} reaggregatable={str(item['reaggregatable']).lower()}",
                f"ALTER SEMANTIC VIEW {view} ADD MATERIALIZATION {item['name']}",
                "  WAREHOUSE = <MATERIALIZATION_WAREHOUSE>",
                f"  REFRESH_MODE = {item['refresh_mode']}",
                "  AS",
                f"    DIMENSIONS {dimensions}" if dimensions else "",
                f"    METRICS {metrics};",
                "",
            ]
        )
    lines.extend(
        [
            f"SHOW MATERIALIZATIONS IN SEMANTIC VIEW {view};",
            "",
        ]
    )
    return "\n".join(line for line in lines if line != "" or True)


def declarative_materializations(plan: dict[str, Any]) -> dict[str, Any]:
    materializations = []
    for item in plan["semantic_sql"]["materializations"]:
        materializations.append(
            {
                "name": item["name"],
                "warehouse": "<MATERIALIZATION_WAREHOUSE>",
                "dimensions": [
                    {"table": "REINSURANCE_PERFORMANCE", "name": name}
                    for name in item["dimensions"]
                ],
                "metrics": [
                    {"table": "REINSURANCE_PERFORMANCE", "name": name}
                    for name in item["metrics"]
                ],
            }
        )
    return {"materializations": materializations}


def render_declarative_sync_sql(plan: dict[str, Any], yaml_text: str) -> str:
    return (
        "-- Declarative materialization reconciliation. Review warehouse placeholder before live execution.\n"
        f"ALTER SEMANTIC VIEW {plan['semantic_view']} SET MAX_STALENESS = {plan['max_staleness_sec']};\n"
        "CALL SYSTEM$MANAGE_SEMANTIC_VIEW_MATERIALIZATIONS_FROM_YAML(\n"
        f"  '{plan['semantic_view']}',\n"
        "  $\n"
        f"{yaml_text.rstrip()}\n"
        "  $\n"
        ");\n"
    )


def generate(output: Path, database: str, contract_path: Path = DEFAULT_CONTRACT) -> list[Path]:
    import yaml

    output.mkdir(parents=True, exist_ok=True)
    plan = build_plan(database, contract_path)
    plan_path = output / "acceleration_plan.json"
    sql_path = output / "semantic_materializations.template.sql"
    yaml_path = output / "semantic_materializations.yml"
    sync_path = output / "sync_semantic_materializations.template.sql"

    desired = declarative_materializations(plan)
    yaml_text = yaml.safe_dump(desired, sort_keys=False, width=120)
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    sql_path.write_text(render_materialization_sql(plan), encoding="utf-8")
    yaml_path.write_text(yaml_text, encoding="utf-8")
    sync_path.write_text(render_declarative_sync_sql(plan, yaml_text), encoding="utf-8")
    return [plan_path, sql_path, yaml_path, sync_path]


def main() -> int:
    args = parse_args()
    files = generate(args.output, args.database, args.contract)
    print(json.dumps({"status": "PASS", "files": [str(path) for path in files]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
