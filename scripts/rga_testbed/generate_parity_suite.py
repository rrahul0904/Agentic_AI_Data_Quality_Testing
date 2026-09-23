#!/usr/bin/env python3
"""Generate cross-consumer semantic parity cases from the canonical contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, semantic_view_fqn
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, semantic_view_fqn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "parity"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def semantic_sql(contract: dict, query: dict) -> str:
    table = contract["table_alias"]
    metrics = ", ".join(f"{table}.{name}" for name in query["metrics"])
    dimensions = ", ".join(f"{table}.{name}" for name in query.get("dimensions", []))
    parts = [
        "select *",
        "from semantic_view(",
        f"  {semantic_view_fqn(contract)}",
        f"  metrics {metrics}",
    ]
    if dimensions:
        parts.append(f"  dimensions {dimensions}")
    parts.append(")")
    return "\n".join(parts) + "\n"


def _dax_identifier(name: str) -> str:
    return str(name).replace("]", "]]")


def _dax_table(name: str) -> str:
    return "'" + str(name).replace("'", "''") + "'"


def power_bi_dax(contract: dict, query: dict) -> str:
    table = _dax_table(contract["table_alias"])
    dimensions = query.get("dimensions", [])
    metrics = query["metrics"]
    if not dimensions:
        args = ",\n    ".join(
            f'\"{_dax_identifier(metric)}\", [{_dax_identifier(metric)}]'
            for metric in metrics
        )
        return "EVALUATE\nROW(\n    " + args + "\n)\n"

    parts = [
        f"{table}[{_dax_identifier(name)}]"
        for name in dimensions
    ]
    parts.extend(
        f'\"{_dax_identifier(metric)}\", [{_dax_identifier(metric)}]'
        for metric in metrics
    )
    return (
        "EVALUATE\nSUMMARIZECOLUMNS(\n    "
        + ",\n    ".join(parts)
        + "\n)\n"
    )


def build_suite(database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict:
    contract = load_semantic_contract(contract_path, database)
    cases = []
    for query in contract["verified_queries"]:
        cases.append(
            {
                "id": query["id"],
                "business_question": query["question"],
                "metrics": query["metrics"],
                "dimensions": query.get("dimensions", []),
                "reference": {
                    "consumer": "snowflake_semantic_view",
                    "semantic_view": semantic_view_fqn(contract),
                    "sql_file": f"{query['id']}.reference.sql",
                },
                "ai": {
                    "consumer": "cortex_agent_mcp",
                    "prompt": query["question"],
                    "must_use_governed_agent": True,
                    "expected_metrics": query["metrics"],
                    "expected_dimensions": query.get("dimensions", []),
                },
                "power_bi": {
                    "consumer": "power_bi",
                    "required_connection_mode": contract["consumers"]["power_bi"]["required_connection_mode"],
                    "expected_metrics": query["metrics"],
                    "expected_dimensions": query.get("dimensions", []),
                    "allow_local_metric_reimplementation": False,
                    "dax_file": f"{query['id']}.powerbi.dax",
                    "capture_api": "executeDaxQueries",
                },
                "excel": {
                    "consumer": "excel",
                    "required_connection_mode": contract["consumers"]["excel"]["required_connection_mode"],
                    "expected_metrics": query["metrics"],
                    "expected_dimensions": query.get("dimensions", []),
                    "allow_local_metric_reimplementation": False,
                },
                "acceptance": {
                    "same_metric_definition": True,
                    "same_dimensional_grain": True,
                    "same_filter_context": True,
                    "same_security_context": True,
                    "numeric_tolerance": 1e-9,
                    "require_captured_evidence": True,
                    "allow_empty_result": False,
                },
            }
        )
    return {
        "name": f"{contract['name'].lower()}_cross_consumer_semantic_parity",
        "canonical_contract": str(contract_path),
        "semantic_view": semantic_view_fqn(contract),
        "required_consumers": ["snowflake_semantic_view", "cortex_agent_mcp", "power_bi", "excel"],
        "cases": cases,
    }


def generate(output: Path, database: str, contract_path: Path = DEFAULT_CONTRACT) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    contract = load_semantic_contract(contract_path, database)
    suite = build_suite(database, contract_path)
    written: list[Path] = []
    for query in contract["verified_queries"]:
        path = output / f"{query['id']}.reference.sql"
        path.write_text(semantic_sql(contract, query), encoding="utf-8")
        written.append(path)

        dax_path = output / f"{query['id']}.powerbi.dax"
        dax_path.write_text(power_bi_dax(contract, query), encoding="utf-8")
        written.append(dax_path)
    manifest = output / "parity_manifest.json"
    manifest.write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
    written.append(manifest)
    return written


def main() -> int:
    args = parse_args()
    files = generate(args.output, args.database, args.contract)
    print(json.dumps({"status": "PASS", "files": [str(path) for path in files]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
