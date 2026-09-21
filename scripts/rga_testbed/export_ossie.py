#!/usr/bin/env python3
"""Export the canonical RGA semantic contract to an Apache Ossie-compatible YAML model.

This is intentionally export-only. Unsupported Snowflake-specific behavior is preserved
under custom_extensions instead of pretending to be portable.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, domain_guidance, load_semantic_contract, mart_fqn
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, domain_guidance, load_semantic_contract, mart_fqn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "interchange" / "rga_reinsurance_performance.ossie.yml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _datatype(value: str) -> str:
    upper = value.upper()
    if "DATE" in upper and "TIME" not in upper:
        return "Date"
    if "TIMESTAMP" in upper:
        return "DateTimeTz"
    if "BOOLEAN" in upper:
        return "Boolean"
    if "INT" in upper:
        return "Integer"
    if "NUMBER" in upper or "DECIMAL" in upper or "FLOAT" in upper:
        return "Decimal"
    return "String"


def _expression(expr: str) -> dict[str, Any]:
    return {"dialects": [{"dialect": "SNOWFLAKE", "expression": expr}]}


def _qualify_metric_expression(expr: str, dataset: str, fact_names: list[str]) -> str:
    result = expr
    for fact in sorted(fact_names, key=len, reverse=True):
        result = re.sub(rf"(?<![A-Z0-9_.]){re.escape(fact)}(?![A-Z0-9_])", f"{dataset}.{fact}", result, flags=re.IGNORECASE)
    return result


def build_ossie_model(database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = load_semantic_contract(contract_path, database)
    dataset_name = contract["table_alias"].lower()
    fields: list[dict[str, Any]] = []

    for item in contract["dimensions"]:
        fields.append(
            {
                "name": item["name"].lower(),
                "expression": _expression(item["expr"]),
                "description": item["description"],
                "datatype": _datatype(item["data_type"]),
                "dimension": {"is_time": False},
                "ai_context": {"synonyms": item.get("synonyms", [])},
            }
        )

    for item in contract["time_dimensions"]:
        fields.append(
            {
                "name": item["name"].lower(),
                "expression": _expression(item["expr"]),
                "description": item["description"],
                "datatype": _datatype(item["data_type"]),
                "dimension": {"is_time": True},
                "ai_context": {"synonyms": item.get("synonyms", [])},
            }
        )

    for item in contract["facts"]:
        fields.append(
            {
                "name": item["name"].lower(),
                "expression": _expression(item["expr"]),
                "datatype": _datatype(item["data_type"]),
            }
        )

    fact_names = [item["name"] for item in contract["facts"]]
    metrics = []
    for item in contract["metrics"]:
        metrics.append(
            {
                "name": item["name"].lower(),
                "description": item["description"],
                "expression": _expression(
                    _qualify_metric_expression(item["expr"], dataset_name, fact_names)
                ),
                "ai_context": {"synonyms": item.get("synonyms", [])},
            }
        )

    extension_payload = {
        "semantic_view_name": contract["name"],
        "verified_queries": contract["verified_queries"],
        "consumers": contract["consumers"],
        "acceleration": contract.get("acceleration", {}),
        "performance": contract["performance"],
    }

    guidance = domain_guidance(contract)
    semantic_model = {
        "name": contract["name"].lower(),
        "description": contract["description"],
        "ai_context": {
            "instructions": guidance["ossie_instructions"]
        },
        "datasets": [
            {
                "name": dataset_name,
                "source": mart_fqn(contract),
                "primary_key": [item.lower() for item in contract["grain"]],
                "unique_keys": [[item.lower() for item in contract["grain"]]],
                "description": guidance["dataset_description"],
                "fields": fields,
            }
        ],
        "metrics": metrics,
        "custom_extensions": [
            {
                "vendor_name": "SNOWFLAKE",
                "data": json.dumps(extension_payload, sort_keys=True),
            }
        ],
    }
    return {
        "version": "0.2.0.dev0",
        "semantic_model": [semantic_model],
    }


def generate(output: Path, database: str, contract_path: Path = DEFAULT_CONTRACT) -> Path:
    model = build_ossie_model(database, contract_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(model, sort_keys=False, width=120), encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    path = generate(args.output, args.database, args.contract)
    print(json.dumps({"status": "PASS", "output": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
