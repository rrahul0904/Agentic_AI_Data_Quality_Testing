#!/usr/bin/env python3
"""Fail-fast ingestion checks for generated local feeds."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from data_generator.generate_file_data import FEEDS

REQUIRED_METADATA = {"load_date", "source_file_name", "source_system", "event_timestamp"}


def rows_for(path: Path) -> Iterator[dict[str, Any]]:
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            yield from csv.DictReader(handle)
    elif path.suffix in {".json", ".jsonl"}:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)
    elif path.suffix == ".parquet":
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=10_000):
            yield from batch.to_pylist()


def validate_file(path: Path, sample_limit: int = 100_000) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty feed: {path}")
    sampled = 0
    invalid_timestamps = 0
    null_business_keys = 0
    duplicate_rows = 0
    fingerprints: Counter[str] = Counter()
    for row in rows_for(path):
        missing = REQUIRED_METADATA - row.keys()
        if missing:
            raise ValueError(f"{path.name} is missing metadata fields: {sorted(missing)}")
        sampled += 1
        try:
            datetime.fromisoformat(str(row["event_timestamp"]))
        except (TypeError, ValueError):
            invalid_timestamps += 1
        if row.get("property_id") in {None, ""}:
            null_business_keys += 1
        fingerprint = json.dumps(row, sort_keys=True, default=str)
        fingerprints[fingerprint] += 1
        if fingerprints[fingerprint] > 1:
            duplicate_rows += 1
        if sampled >= sample_limit:
            break
    if sampled == 0:
        raise ValueError(f"Feed has no data rows: {path}")
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sampled_rows": sampled,
        "invalid_timestamps": invalid_timestamps,
        "null_business_keys": null_business_keys,
        "duplicate_rows": duplicate_rows,
        "status": "PASS_WITH_QUARANTINE_CANDIDATES"
        if invalid_timestamps or null_business_keys or duplicate_rows
        else "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    results = [validate_file(args.directory / filename) for filename in FEEDS]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
