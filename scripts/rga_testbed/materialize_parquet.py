#!/usr/bin/env python3
"""Materialize deterministic RGA CSV shards to Parquet with bounded DuckDB memory."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--row-group-size", type=int, default=100000)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sql_string(value: str) -> str:
    return value.replace("'", "''")


def materialize(
    input_root: Path,
    output_root: Path,
    *,
    memory_limit: str = "512MB",
    row_group_size: int = 100000,
) -> dict[str, Any]:
    if row_group_size < 1000:
        raise ValueError("row_group_size must be at least 1000")
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "duckdb is required for bounded-memory Parquet materialization"
        ) from exc

    manifest_path = input_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    temp_dir = output_root / ".duckdb_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(database=":memory:")
    files: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    try:
        connection.execute(
            f"SET memory_limit='{_sql_string(memory_limit)}'"
        )
        connection.execute(
            f"SET temp_directory='{_sql_string(temp_dir.resolve().as_posix())}'"
        )
        connection.execute("SET preserve_insertion_order=false")

        for source in manifest.get("files", []):
            entity = str(source["entity"])
            csv_path = input_root / source["file"]
            if not csv_path.exists():
                raise FileNotFoundError(f"source CSV not found: {csv_path}")

            entity_dir = output_root / entity
            entity_dir.mkdir(parents=True, exist_ok=True)
            parquet_path = entity_dir / (csv_path.stem + ".parquet")

            source_sql = _sql_string(csv_path.resolve().as_posix())
            target_sql = _sql_string(parquet_path.resolve().as_posix())
            connection.execute(
                f"""
copy (
  select *
  from read_csv_auto(
    '{source_sql}',
    header=true,
    union_by_name=true
  )
)
to '{target_sql}'
(format parquet, compression zstd, row_group_size {int(row_group_size)})
"""
            )
            row_count = int(
                connection.execute(
                    f"select count(*) from read_parquet('{target_sql}')"
                ).fetchone()[0]
            )
            expected = int(source["row_count"])
            if row_count != expected:
                raise RuntimeError(
                    f"Parquet row count mismatch for {entity}: "
                    f"expected={expected} actual={row_count}"
                )
            counts[entity] = counts.get(entity, 0) + row_count
            files.append(
                {
                    "entity": entity,
                    "source_file": source["file"],
                    "file": parquet_path.relative_to(output_root).as_posix(),
                    "row_count": row_count,
                    "byte_count": parquet_path.stat().st_size,
                    "checksum": sha256(parquet_path),
                    "compression": "zstd",
                }
            )
    finally:
        connection.close()
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    expected_counts = {
        str(entity): int(count)
        for entity, count in manifest.get("counts", {}).items()
    }
    if counts != expected_counts:
        raise RuntimeError(
            f"Parquet entity counts do not match source manifest: "
            f"expected={expected_counts} actual={counts}"
        )

    result = {
        "status": "PASS",
        "source_generation_id": manifest["generation_id"],
        "source_manifest": str(manifest_path),
        "memory_limit": memory_limit,
        "row_group_size": row_group_size,
        "format": "parquet",
        "compression": "zstd",
        "counts": counts,
        "file_count": len(files),
        "total_bytes": sum(item["byte_count"] for item in files),
        "files": files,
        "scope": (
            "Parquet is derived from the certified deterministic CSV shards. "
            "This step validates row-count parity and file checksums; it does "
            "not replace live warehouse-load certification."
        ),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    args = parse_args()
    try:
        result = materialize(
            args.input,
            args.output,
            memory_limit=args.memory_limit,
            row_group_size=args.row_group_size,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
