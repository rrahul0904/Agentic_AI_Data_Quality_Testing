#!/usr/bin/env python3
"""Generate paired MART and Semantic View benchmark queries from the canonical semantic contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, mart_fqn, semantic_view_fqn
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, mart_fqn, semantic_view_fqn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "benchmarks"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def _lookup(items: list[dict], name: str) -> dict:
    for item in items:
        if item["name"] == name:
            return item
    raise KeyError(name)


def _direct_sql(contract: dict, query: dict) -> str:
    dimensions = query.get("dimensions", [])
    dimension_exprs = [_lookup(contract["dimensions"] + contract["time_dimensions"], name)["expr"] for name in dimensions]
    metric_exprs = [
        f"{_lookup(contract['metrics'], name)['expr']} as {name.lower()}"
        for name in query["metrics"]
    ]
    selects = dimension_exprs + metric_exprs
    lines = ["select", "    " + ",\n    ".join(selects), f"from {mart_fqn(contract)}"]
    if dimension_exprs:
        ordinals = ", ".join(str(index) for index in range(1, len(dimension_exprs) + 1))
        lines.extend([f"group by {ordinals}", f"order by {ordinals}"])
    return "\n".join(lines) + "\n"


def _semantic_sql(contract: dict, query: dict) -> str:
    table = contract["table_alias"]
    metrics = ",\n          ".join(f"{table}.{name}" for name in query["metrics"])
    dimensions = ", ".join(f"{table}.{name}" for name in query.get("dimensions", []))
    lines = [
        "select *",
        "from semantic_view(",
        f"  {semantic_view_fqn(contract)}",
        f"  metrics {metrics}",
    ]
    if dimensions:
        lines.append(f"  dimensions {dimensions}")
    lines.append(")")
    return "\n".join(lines) + "\n"


def build_queries(database: str, contract_path: Path = DEFAULT_CONTRACT) -> list[dict[str, str]]:
    contract = load_semantic_contract(contract_path, database)
    return [
        {
            "id": query["id"],
            "question": query["question"],
            "metrics": query["metrics"],
            "dimensions": query.get("dimensions", []),
            "direct_sql": _direct_sql(contract, query),
            "semantic_sql": _semantic_sql(contract, query),
        }
        for query in contract["verified_queries"]
    ]


def generate(output: Path, database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    contract = load_semantic_contract(contract_path, database)
    entries = []
    for query in build_queries(database, contract_path):
        direct_path = output / f"{query['id']}.direct.sql"
        semantic_path = output / f"{query['id']}.semantic.sql"
        direct_path.write_text(query["direct_sql"].rstrip() + "\n", encoding="utf-8")
        semantic_path.write_text(query["semantic_sql"].rstrip() + "\n", encoding="utf-8")
        entries.append(
            {
                "id": query["id"],
                "question": query["question"],
                "metrics": query["metrics"],
                "dimensions": query["dimensions"],
                "direct_sql": direct_path.name,
                "semantic_sql": semantic_path.name,
            }
        )
    manifest = {
        "name": "rga_semantic_performance_benchmark",
        "database": database,
        "semantic_contract": str(contract_path),
        "semantic_view": semantic_view_fqn(contract),
        "query_tag": "RGA_SEMANTIC_BENCHMARK",
        "queries": entries,
        "recommended_concurrency": contract["performance"]["concurrency"],
        "acceptance": {
            "target_p95_ms": contract["performance"]["target_p95_ms"],
            "max_remote_spill_bytes": contract["performance"]["max_remote_spill_bytes"],
        },
        "measurements": contract["performance"]["collect"],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    args = parse_args()
    manifest = generate(args.output, args.database, args.contract)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
