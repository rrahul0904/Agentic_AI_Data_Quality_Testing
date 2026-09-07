"""Immutable local landing for extracted source artifacts."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def land(ti: Any, **_: Any) -> list[dict[str, Any]]:
    batch = ti.xcom_pull(task_ids="create_batch")
    artifacts = ti.xcom_pull(task_ids="extract")
    landing_dir = Path(os.environ.get("LOCAL_LANDING_DIR", "/opt/airflow/data/landing")) / batch["batch_id"] / "landed"
    landing_dir.mkdir(parents=True, exist_ok=False)
    landed: list[dict[str, Any]] = []
    for artifact in artifacts:
        source = Path(artifact["source_path"])
        destination = landing_dir / source.name
        with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
        landed.append({**artifact, "landed_path": str(destination)})
    return landed
