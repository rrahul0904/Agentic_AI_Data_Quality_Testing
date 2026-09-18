#!/usr/bin/env python3
"""Generate a native Snowflake Semantic View from the canonical governed contract."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

try:
    from scripts.rga_testbed.semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, semantic_view_fqn
except ModuleNotFoundError:
    from semantic_contract import DEFAULT_CONTRACT, load_semantic_contract, semantic_view_fqn

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "rga-snowflake-data-platform" / "semantic"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def _semantic_query(contract: dict, query: dict) -> str:
    table = contract["table_alias"]
    metrics = ", ".join(f"{table}.{name}" for name in query["metrics"])
    dimensions = ", ".join(f"{table}.{name}" for name in query.get("dimensions", []))
    parts = [f"SELECT * FROM SEMANTIC_VIEW({semantic_view_fqn(contract)}", f"METRICS {metrics}"]
    if dimensions:
        parts.append(f"DIMENSIONS {dimensions}")
    return " ".join(parts) + ")"


def build_semantic_spec(database: str, contract_path: Path = DEFAULT_CONTRACT) -> dict:
    contract = load_semantic_contract(contract_path, database)
    return {
        "name": contract["name"],
        "description": contract["description"],
        "max_staleness": int(contract.get("acceleration", {}).get("semantic_sql", {}).get("max_staleness_sec", 3600)),
        "tables": [
            {
                "name": contract["table_alias"],
                "description": "Monthly cedant and treaty performance at the governed contract grain.",
                "base_table": {
                    "database": contract["database"],
                    "schema": contract["mart_schema"],
                    "table": contract["mart_table"],
                },
                "primary_key": {"columns": contract["grain"]},
                "dimensions": contract["dimensions"],
                "time_dimensions": contract["time_dimensions"],
                "facts": contract["facts"],
                "metrics": contract["metrics"],
            }
        ],
        "verified_queries": [
            {
                "name": query["id"],
                "question": query["question"],
                "sql": _semantic_query(contract, query),
                "use_as_onboarding_question": bool(query.get("use_as_onboarding_question", False)),
            }
            for query in contract["verified_queries"]
        ],
    }


def render_sql(database: str, semantic_schema: str, yaml_text: str, verify_only: bool) -> str:
    verify = "TRUE" if verify_only else "FALSE"
    return (
        "CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(\n"
        f"  '{database}.{semantic_schema}',\n"
        "  $$\n"
        f"{yaml_text.rstrip()}\n"
        "  $$,\n"
        f"  {verify},\n"
        "  TRUE\n"
        ");\n"
    )


def generate(output: Path, database: str, contract_path: Path = DEFAULT_CONTRACT) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    contract = load_semantic_contract(contract_path, database)
    spec = build_semantic_spec(database, contract_path)
    yaml_text = yaml.safe_dump(spec, sort_keys=False, width=120)
    stem = contract["name"].lower()
    files = [
        (output / f"{stem}.yml", yaml_text),
        (output / "verify_semantic_view.sql", render_sql(database, contract["semantic_schema"], yaml_text, True)),
        (output / "deploy_semantic_view.sql", render_sql(database, contract["semantic_schema"], yaml_text, False)),
    ]
    for path, text in files:
        path.write_text(text, encoding="utf-8")
    return [path for path, _ in files]


def main() -> int:
    args = parse_args()
    files = generate(args.output, args.database, args.contract)
    for path in files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
