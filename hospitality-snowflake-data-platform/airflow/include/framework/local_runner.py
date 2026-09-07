"""Run the same ingestion callables without an Airflow scheduler."""

from __future__ import annotations

import os
from typing import Any

from .audit import audit_batch
from .batch import create_batch
from .extractor import extract
from .landing import land
from .quality import quality_gate
from .reconciliation import reconcile
from .snowflake_loader import copy_raw, stage
from .validator import validate
from .watermark import read_watermark, update_watermark


class _MemoryTaskInstance:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def xcom_pull(self, task_ids: str) -> Any:
        return self.values.get(task_ids)

    def record(self, task_id: str, value: Any) -> Any:
        self.values[task_id] = value
        return value


def run_local_job(job: dict[str, Any]) -> dict[str, Any]:
    os.environ["HOSPITALITY_EXECUTION_MODE"] = "local"
    ti = _MemoryTaskInstance()
    ti.record("create_batch", create_batch(job))
    ti.record("read_watermark", read_watermark(job))
    ti.record("extract", extract(job, ti))
    ti.record("land", land(ti))
    ti.record("validate", validate(ti))
    ti.record("stage", stage(job, ti))
    ti.record("copy_raw", copy_raw(job, ti))
    ti.record("reconcile", reconcile(ti))
    ti.record("quality_gate", quality_gate(ti))
    ti.record("update_watermark", update_watermark(job, ti))
    ti.record("audit", audit_batch(ti))
    return {
        "batch": ti.values["create_batch"],
        "reconciliation": ti.values["reconcile"],
        "quality": ti.values["quality_gate"],
        "audit": ti.values["audit"],
    }
