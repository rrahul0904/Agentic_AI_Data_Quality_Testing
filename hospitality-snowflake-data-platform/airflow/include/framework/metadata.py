"""Typed metadata contracts consumed by the DAG factory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class IngestionJob:
    dag_id: str
    source: str
    entities: tuple[str, ...]
    load_strategy: str = "timestamp_incremental"
    schedule: str | None = "15 2 * * *"

    def as_mapping(self) -> dict[str, Any]:
        value = asdict(self)
        value["entities"] = list(self.entities)
        return value


def normalize_job(job: IngestionJob | dict[str, Any]) -> dict[str, Any]:
    value = job.as_mapping() if isinstance(job, IngestionJob) else dict(job)
    required = {"dag_id", "source", "entities", "load_strategy"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"Ingestion job is missing fields: {sorted(missing)}")
    if value["source"] not in {"oracle", "postgres", "files"}:
        raise ValueError(f"Unsupported ingestion source: {value['source']!r}")
    if not value["entities"]:
        raise ValueError("Ingestion job must contain at least one entity")
    return value
