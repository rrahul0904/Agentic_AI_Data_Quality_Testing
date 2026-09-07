"""Batch identity creation and audit initialization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .audit import begin_batch
from .metadata import normalize_job


def create_batch(job: dict[str, Any], dag_run: Any = None, **_: Any) -> dict[str, Any]:
    spec = normalize_job(job)
    batch = {
        **spec,
        "batch_id": f"{spec['source']}-{spec['dag_id']}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}",
        "run_id": getattr(dag_run, "run_id", None),
        "created_at": datetime.now(UTC).isoformat(),
    }
    begin_batch(batch)
    return batch
