"""Normalize version-varying Airflow REST payloads into ADE evidence contracts."""

from __future__ import annotations

from typing import Any, Iterable

from agentic_data_platform.agents.contracts import ExecutionLifecycleEvidence


def availability(payload: dict[str, Any]) -> dict[str, str]:
    status = str(payload.get("status") or "").upper()
    http_status = payload.get("http_status")
    if status == "SKIP_EXTERNAL":
        return {"status": "UNAVAILABLE", "reason": str(payload.get("reason") or "Airflow is not configured.")}
    if http_status in {401, 403}:
        return {"status": "PERMISSION_DENIED", "reason": str(payload.get("error") or "Airflow denied access.")}
    if status == "ERROR":
        return {"status": "UNAVAILABLE", "reason": str(payload.get("error") or "Airflow request failed.")}
    if status == "UNSUPPORTED":
        return {"status": "UNSUPPORTED", "reason": str(payload.get("reason") or "Endpoint is unsupported.")}
    return {"status": "AVAILABLE", "reason": "Live Airflow API returned data."}


def collection(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def normalize_task_instance(
    item: dict[str, Any],
    *,
    dag_id: str | None = None,
    run_id: str | None = None,
    evidence_ids: Iterable[str] = (),
) -> ExecutionLifecycleEvidence:
    queued_at = item.get("queued_when") or item.get("queued_at") or item.get("queued_dttm")
    running_at = item.get("start_date") or item.get("startDate")
    ended_at = item.get("end_date") or item.get("endDate")
    state = str(item.get("state") or "UNKNOWN").upper()
    return ExecutionLifecycleEvidence(
        task_id=str(item.get("task_id") or item.get("taskId") or "unknown-task"),
        run_id=str(run_id or item.get("dag_run_id") or item.get("dagRunId") or "unknown-run"),
        dag_id=str(dag_id or item.get("dag_id") or item.get("dagId") or "unknown-dag"),
        queued_at=str(queued_at) if queued_at else None,
        running_at=str(running_at) if running_at else None,
        ended_at=str(ended_at) if ended_at else None,
        metadata_state=state,
        task_log_exists=None,
        runtime_start_proven=bool(running_at),
        operator_start_proven=False,
        try_number=item.get("try_number") or item.get("tryNumber"),
        mapped_task_index=item.get("map_index") if item.get("map_index") is not None else item.get("mapIndex"),
        pool=item.get("pool"),
        queue=item.get("queue"),
        priority=item.get("priority_weight") or item.get("priorityWeight"),
        queued_duration_seconds=_duration(item.get("queued_duration") or item.get("queuedDuration")),
        evidence_ids=tuple(evidence_ids),
    )


def _duration(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
