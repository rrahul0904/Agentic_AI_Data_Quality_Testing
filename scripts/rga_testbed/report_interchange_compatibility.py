#!/usr/bin/env python3
"""Report what is portable to Apache Ossie and what remains Snowflake-specific."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, load_semantic_contract
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, load_semantic_contract

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "interchange" / "ossie_compatibility.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def build_report(database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict:
    contract = load_semantic_contract(contract_path, database)
    portable = [
        "dataset",
        "grain_primary_key",
        "dimensions",
        "time_dimensions",
        "facts_as_fields",
        "metrics",
        "descriptions",
        "synonyms",
    ]
    extensions = [
        "verified_queries",
        "consumer_policies",
        "semantic_view_materialization_policy",
        "cortex_agent_policy",
        "power_bi_excel_live_connection_requirements",
        "performance_acceptance",
    ]
    return {
        "format": "apache_ossie",
        "direction": "export",
        "status": "SUPPORTED_WITH_EXTENSIONS",
        "lossless_core": portable,
        "preserved_as_custom_extensions": extensions,
        "not_exported": [],
        "round_trip_import_supported": False,
        "round_trip_reason": (
            "Import is intentionally disabled until Snowflake-specific custom extensions "
            "can be validated and reconstructed without silent semantic loss."
        ),
        "source_metric_count": len(contract["metrics"]),
        "source_dimension_count": len(contract["dimensions"]) + len(contract["time_dimensions"]),
    }


def main() -> int:
    args = parse_args()
    report = build_report(args.database, args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output), "compatibility": report["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
