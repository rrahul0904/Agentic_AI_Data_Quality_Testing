"""Streaming artifact validation and deterministic artifact metadata."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from include.configs.file_schemas import FILE_SCHEMAS


def _line_metadata(path: Path) -> tuple[int, str | None]:
    rows = 0
    watermark: str | None = None
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = tuple(next(reader, ()))
            expected = FILE_SCHEMAS.get(path.name)
            if expected and header != expected:
                raise ValueError(f"Schema mismatch for {path.name}: expected {expected}, got {header}")
            rows = sum(1 for _ in reader)
    elif path.suffix.lower() in {".json", ".jsonl"}:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON in {path.name} at line {line_number}: {exc.msg}") from exc
                rows += 1
                candidate = value.get("SOURCE_UPDATED_AT") or value.get("source_updated_at")
                if candidate is not None and (watermark is None or str(candidate) > watermark):
                    watermark = str(candidate)
    elif path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq

        rows = pq.ParquetFile(path).metadata.num_rows
    else:
        raise ValueError(f"Unsupported artifact format: {path}")
    return rows, watermark


def validate(ti: Any, **_: Any) -> dict[str, Any]:
    artifacts = ti.xcom_pull(task_ids="land")
    results = []
    for artifact in artifacts:
        path = Path(artifact["landed_path"])
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Artifact is absent or empty: {path}")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
        rows, watermark = _line_metadata(path)
        if rows <= 0:
            raise ValueError(f"Artifact has no data rows: {path}")
        results.append(
            {
                **artifact,
                "bytes": path.stat().st_size,
                "rows": rows,
                "sha256": hasher.hexdigest(),
                "watermark_end": watermark,
            }
        )
    return {"artifacts": results}
