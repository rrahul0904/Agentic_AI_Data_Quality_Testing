#!/usr/bin/env python3
"""Compile the RGA synthetic domain contract into Snowflake RAW table DDL."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "rga_domain.yml"
DEFAULT_OUTPUT = ROOT / "snowflake" / "rga_testbed" / "001_raw_tables.sql"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def compile_ddl(config: dict[str, Any], database: str) -> str:
    statements = [
        f"CREATE DATABASE IF NOT EXISTS {database};",
        f"USE DATABASE {database};",
        "CREATE SCHEMA IF NOT EXISTS RAW;",
        "CREATE SCHEMA IF NOT EXISTS STAGING;",
        "CREATE SCHEMA IF NOT EXISTS CORE;",
        "CREATE SCHEMA IF NOT EXISTS MART;",
        "CREATE SCHEMA IF NOT EXISTS SEMANTIC;",
        "CREATE SCHEMA IF NOT EXISTS AI;",
        "CREATE SCHEMA IF NOT EXISTS AUDIT;",
        "CREATE FILE FORMAT IF NOT EXISTS RAW.FF_RGA_CSV_HEADER TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='\"' NULL_IF=('','NULL');",
        "CREATE FILE FORMAT IF NOT EXISTS RAW.FF_RGA_JSON TYPE=JSON STRIP_OUTER_ARRAY=FALSE;",
        "CREATE STAGE IF NOT EXISTS RAW.RGA_INTERNAL_STAGE FILE_FORMAT=RAW.FF_RGA_CSV_HEADER;",
        "CREATE STAGE IF NOT EXISTS RAW.RGA_CDC_STAGE FILE_FORMAT=RAW.FF_RGA_JSON;",
        "CREATE TABLE IF NOT EXISTS RAW.RGA_CDC_EVENTS (",
        "    EVENT VARIANT NOT NULL,",
        "    _SOURCE_FILE VARCHAR,",
        "    _INGESTED_AT TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()",
        ");",
        "",
    ]
    for spec in config["entities"].values():
        schema, table = spec["target"].split(".", 1)
        columns = [f"    {name.upper()} {dtype}" for name, dtype in spec["columns"].items()]
        columns.extend(
            [
                "    _GENERATION_ID VARCHAR NOT NULL",
                "    _SOURCE_FILE VARCHAR",
                "    _INGESTED_AT TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()",
            ]
        )
        body = ",\n".join(columns)
        statements.append(f"CREATE TABLE IF NOT EXISTS {schema}.{table} (\n{body}\n);")
        statements.append(
            f"COMMENT ON TABLE {schema}.{table} IS 'Synthetic RGA-like test data only; no proprietary or real-person data';"
        )
        statements.append("")
    statements.extend(
        [
            "CREATE TABLE IF NOT EXISTS AUDIT.SYNTHETIC_GENERATION_MANIFEST (",
            "    GENERATION_ID VARCHAR PRIMARY KEY,",
            "    DOMAIN VARCHAR NOT NULL,",
            "    PRESET VARCHAR NOT NULL,",
            "    SEED NUMBER NOT NULL,",
            "    REFERENCE_DATE DATE NOT NULL,",
            "    MANIFEST VARIANT NOT NULL,",
            "    CREATED_AT TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP()",
            ");",
            "",
            "CREATE TABLE IF NOT EXISTS AUDIT.CDC_EVENT_APPLICATIONS (",
            "    EVENT_ID VARCHAR NOT NULL,",
            "    ENTITY VARCHAR NOT NULL,",
            "    OPERATION VARCHAR NOT NULL,",
            "    BUSINESS_KEY VARCHAR NOT NULL,",
            "    SCENARIO VARCHAR NOT NULL,",
            "    EFFECTIVE_AT TIMESTAMP_TZ,",
            "    SOURCE_FILE VARCHAR,",
            "    STATUS VARCHAR NOT NULL,",
            "    APPLIED_AT TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),",
            "    EVENT VARIANT NOT NULL,",
            "    PRIMARY KEY (EVENT_ID)",
            ");",
        ]
    )
    return "\n".join(statements).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    ddl = compile_ddl(load_config(args.config), args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(ddl, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
