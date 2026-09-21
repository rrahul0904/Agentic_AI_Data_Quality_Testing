#!/usr/bin/env python3
"""Out-of-core DuckDB validation for large RGA synthetic datasets."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "rga_domain.yml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--keep-temp", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if config.get("domain") != "rga_life_health_reinsurance":
        raise ValueError("Unexpected RGA domain configuration")
    return config


def _sql_string(value: str) -> str:
    return value.replace("'", "''")


def _ident(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return '"' + value.replace('"', '""') + '"'


def _csv_glob(root: Path, entity: str) -> str:
    return (root / "csv" / entity / "*.csv").resolve().as_posix()


def _count_csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _scalar(connection: Any, sql: str) -> Any:
    return connection.execute(sql).fetchone()[0]


def validate(
    root: Path,
    *,
    config_path: Path = DEFAULT_CONFIG,
    memory_limit: str = "512MB",
    keep_temp: bool = False,
) -> dict[str, Any]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "duckdb is required for out-of-core scale validation"
        ) from exc

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = load_config(config_path)
    errors: list[str] = []
    observed_counts: dict[str, int] = {}

    temp_dir = root / ".duckdb_validation_tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            f"SET memory_limit='{_sql_string(memory_limit)}'"
        )
        connection.execute(
            f"SET temp_directory='{_sql_string(temp_dir.resolve().as_posix())}'"
        )
        connection.execute("SET preserve_insertion_order=false")

        # File-level evidence stays streaming and bounded in Python.
        for item in manifest.get("files", []):
            path = root / item["file"]
            if not path.exists():
                errors.append(f"missing file: {item['file']}")
                continue
            if sha256(path) != item["checksum"]:
                errors.append(f"checksum mismatch: {item['file']}")
            count = _count_csv_rows(path)
            if count != int(item["row_count"]):
                errors.append(
                    f"row count mismatch: {item['file']} "
                    f"expected={item['row_count']} actual={count}"
                )

        # DuckDB scans relational data out-of-core and can spill joins/grouping.
        for entity, spec in config["entities"].items():
            files = sorted((root / "csv" / entity).glob("*.csv"))
            if not files:
                expected = int(manifest.get("counts", {}).get(entity, 0))
                if expected:
                    errors.append(f"missing CSV files for entity {entity}")
                observed_counts[entity] = 0
                continue
            view = _ident(entity)
            glob = _sql_string(_csv_glob(root, entity))
            connection.execute(
                f"""
create or replace view {view} as
select *
from read_csv_auto(
  '{glob}',
  header=true,
  all_varchar=true,
  union_by_name=true
)
"""
            )
            count = int(_scalar(connection, f"select count(*) from {view}"))
            observed_counts[entity] = count

            business_key = _ident(spec["business_key"])
            duplicate_count = int(
                _scalar(
                    connection,
                    f"""
select count(*)
from (
  select {business_key}
  from {view}
  group by {business_key}
  having {business_key} is null
      or trim({business_key}) = ''
      or count(*) > 1
)
""",
                )
            )
            if duplicate_count:
                errors.append(
                    f"{entity} has {duplicate_count} null/blank/duplicate "
                    f"business keys"
                )

            generation_ids = int(
                _scalar(
                    connection,
                    f"""
select count(distinct "_generation_id")
from {view}
where "_generation_id" is not null
""",
                )
            )
            if count and generation_ids != 1:
                errors.append(
                    f"{entity} has {generation_ids} generation IDs; expected 1"
                )

        # General FK validation from the domain contract.
        for entity, spec in config["entities"].items():
            child_view = _ident(entity)
            for child_column, parent_ref in spec.get(
                "foreign_keys", {}
            ).items():
                parent_entity, parent_column = parent_ref.split(".", 1)
                parent_view = _ident(parent_entity)
                child_key = _ident(child_column)
                parent_key = _ident(parent_column)
                missing = int(
                    _scalar(
                        connection,
                        f"""
select count(*)
from {child_view} c
left join {parent_view} p
  on c.{child_key} = p.{parent_key}
where p.{parent_key} is null
""",
                    )
                )
                if missing:
                    errors.append(
                        f"{entity}.{child_column} has {missing} missing "
                        f"references to {parent_ref}"
                    )

        # Domain-specific economic/chronology checks.
        policy_errors = int(
            _scalar(
                connection,
                """
select count(*)
from "policies"
where try_cast("sum_assured" as double) <= 0
   or try_cast("annual_premium" as double) <= 0
""",
            )
        )
        if policy_errors:
            errors.append(
                f"policies has {policy_errors} rows with non-positive economics"
            )

        claim_chronology = int(
            _scalar(
                connection,
                """
select count(*)
from "claims"
where try_cast("reported_date" as date)
    < try_cast("event_date" as date)
""",
            )
        )
        if claim_chronology:
            errors.append(
                f"claims has {claim_chronology} rows reported before event"
            )

        claim_economics = int(
            _scalar(
                connection,
                """
select count(*)
from "claims"
where try_cast("ceded_claim_amount" as double)
    > try_cast("claim_amount" as double)
""",
            )
        )
        if claim_economics:
            errors.append(
                f"claims has {claim_economics} rows with ceded amount "
                "greater than gross claim"
            )

        premium_economics = int(
            _scalar(
                connection,
                """
select count(*)
from "premiums"
where try_cast("gross_premium" as double) < 0
   or try_cast("ceded_premium" as double) < 0
   or try_cast("ceded_premium" as double)
      > try_cast("gross_premium" as double)
""",
            )
        )
        if premium_economics:
            errors.append(
                f"premiums has {premium_economics} invalid gross/ceded rows"
            )

        expected = manifest.get("counts", {})
        for entity, count in expected.items():
            actual = observed_counts.get(entity, 0)
            if actual != int(count):
                errors.append(
                    f"manifest count mismatch for {entity}: "
                    f"expected={count} actual={actual}"
                )
    finally:
        connection.close()
        if not keep_temp and temp_dir.exists():
            shutil.rmtree(temp_dir)

    return {
        "status": "PASS" if not errors else "FAIL",
        "engine": "duckdb_out_of_core",
        "memory_limit": memory_limit,
        "errors": errors,
        "counts": observed_counts,
        "scope": (
            "File checksums/counts, business-key uniqueness, all configured "
            "foreign keys, generation consistency, and core economic/chronology "
            "invariants. DuckDB may spill to disk under the configured memory limit."
        ),
    }


def main() -> int:
    args = parse_args()
    try:
        result = validate(
            args.input,
            config_path=args.config,
            memory_limit=args.memory_limit,
            keep_temp=args.keep_temp,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
