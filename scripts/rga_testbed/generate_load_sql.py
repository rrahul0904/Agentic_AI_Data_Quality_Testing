#!/usr/bin/env python3
"""Generate Snowflake PUT/COPY commands from the RGA domain contract."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "rga_domain.yml"
DEFAULT_OUTPUT = ROOT / "snowflake" / "rga_testbed" / "002_load_raw.sql"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    parser.add_argument("--local-root", default="artifacts/rga_testbed/csv")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def compile_load_sql(config: dict[str, Any], database: str, local_root: str) -> str:
    statements = [f"USE DATABASE {database};", "USE SCHEMA RAW;", ""]
    for entity, spec in config["entities"].items():
        schema, table = spec["target"].split(".", 1)
        column_names = list(spec["columns"])
        stage_path = entity
        statements.append(
            f"PUT 'file://{local_root}/{entity}/*.csv' @RAW.RGA_INTERNAL_STAGE/{stage_path} "
            "AUTO_COMPRESS=TRUE OVERWRITE=TRUE;"
        )
        target_columns = [name.upper() for name in column_names] + ["_GENERATION_ID", "_SOURCE_FILE", "_INGESTED_AT"]
        projections = [f"${idx}::{dtype}" for idx, dtype in enumerate(spec["columns"].values(), 1)]
        projections += [f"${len(column_names) + 1}::VARCHAR", "METADATA$FILENAME", "CURRENT_TIMESTAMP()"]
        statements.append(
            f"COPY INTO {schema}.{table} ({', '.join(target_columns)})\n"
            f"FROM (SELECT {', '.join(projections)} FROM @RAW.RGA_INTERNAL_STAGE/{stage_path})\n"
            "FILE_FORMAT=(FORMAT_NAME=RAW.FF_RGA_CSV_HEADER)\n"
            "PATTERN='.*[.]csv([.]gz)?$'\n"
            "ON_ERROR='ABORT_STATEMENT'\n"
            "FORCE=FALSE;"
        )
        statements.append("")
    return "\n".join(statements).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    sql = compile_load_sql(load_config(args.config), args.database, args.local_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(sql, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
