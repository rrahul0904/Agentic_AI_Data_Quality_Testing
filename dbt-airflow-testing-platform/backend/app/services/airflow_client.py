"""Thin wrapper over the Airflow stable REST API (/api/v1).

We deliberately talk to Airflow the same way a human or CI job would --
trigger a DAG run, poll its state, read task instances -- rather than
importing Airflow internals into this process. That keeps this backend
decoupled from whatever Airflow version/deployment the user actually runs
(consistent with the "environment awareness" pattern used for the dbt leg).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from requests.auth import HTTPBasicAuth

TERMINAL_STATES = {"success", "failed"}


class AirflowUnreachableError(RuntimeError):
    pass


@dataclass
class AirflowTaskInstance:
    task_id: str
    state: str
    duration: float | None
    try_number: int


@dataclass
class AirflowDagRunOutcome:
    dag_id: str
    dag_run_id: str | None
    state: str  # queued | running | success | failed | UNREACHABLE
    logical_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    tasks: list[AirflowTaskInstance] = field(default_factory=list)
    raw_dag_run_json: str | None = None
    raw_task_instances_json: str | None = None
    error: str | None = None


class AirflowClient:
    def __init__(self, base_url: str, username: str, password: str, timeout_seconds: int = 10):
        self.base_url = base_url.rstrip("/")
        self.auth = HTTPBasicAuth(username, password)
        self.timeout_seconds = timeout_seconds

    def _get(self, path: str, **kwargs) -> requests.Response:
        return requests.get(f"{self.base_url}{path}", auth=self.auth, timeout=self.timeout_seconds, **kwargs)

    def _post(self, path: str, **kwargs) -> requests.Response:
        return requests.post(f"{self.base_url}{path}", auth=self.auth, timeout=self.timeout_seconds, **kwargs)

    def health_check(self) -> bool:
        try:
            resp = self._get("/api/v1/health")
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def set_dag_paused(self, dag_id: str, is_paused: bool) -> None:
        resp = requests.patch(
            f"{self.base_url}/api/v1/dags/{dag_id}",
            auth=self.auth,
            timeout=self.timeout_seconds,
            params={"update_mask": "is_paused"},
            json={"is_paused": is_paused},
        )
        if resp.status_code >= 300:
            raise AirflowUnreachableError(f"set_dag_paused failed ({resp.status_code}): {resp.text[:500]}")

    def trigger_dag_run(self, dag_id: str, conf: dict | None = None) -> str:
        payload: dict = {}
        if conf:
            payload["conf"] = conf
        resp = self._post(f"/api/v1/dags/{dag_id}/dagRuns", json=payload)
        if resp.status_code >= 300:
            raise AirflowUnreachableError(f"trigger_dag_run failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json()["dag_run_id"]

    def get_dag_run(self, dag_id: str, dag_run_id: str) -> dict:
        resp = self._get(f"/api/v1/dags/{dag_id}/dagRuns/{dag_run_id}")
        if resp.status_code >= 300:
            raise AirflowUnreachableError(f"get_dag_run failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json()

    def list_task_instances(self, dag_id: str, dag_run_id: str) -> list[dict]:
        resp = self._get(f"/api/v1/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances")
        if resp.status_code >= 300:
            raise AirflowUnreachableError(f"list_task_instances failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json().get("task_instances", [])

    def list_dags(self) -> list[dict]:
        """Discovers every DAG this Airflow instance's DagBag has parsed."""
        resp = self._get("/api/v1/dags", params={"limit": 100})
        if resp.status_code >= 300:
            raise AirflowUnreachableError(f"list_dags failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json().get("dags", [])

    def get_dag_tasks(self, dag_id: str) -> list[dict]:
        """Each task's `downstream_task_ids` gives us the dependency graph."""
        resp = self._get(f"/api/v1/dags/{dag_id}/tasks")
        if resp.status_code >= 300:
            raise AirflowUnreachableError(f"get_dag_tasks failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json().get("tasks", [])

    def run_dag_to_completion(
        self,
        dag_id: str,
        conf: dict | None = None,
        poll_interval_seconds: float = 2.0,
        timeout_seconds: int = 600,
    ) -> AirflowDagRunOutcome:
        if not self.health_check():
            return AirflowDagRunOutcome(
                dag_id=dag_id,
                dag_run_id=None,
                state="UNREACHABLE",
                error=f"Airflow not reachable at {self.base_url}. Start Airflow "
                "(see docs/RUNBOOK.md) or leave it stopped to run dbt-only test runs.",
            )

        try:
            # A manually-triggered run of a *paused* DAG is created but never
            # picked up by the scheduler (sits in "queued" forever) -- a real
            # gotcha hit while testing this against a freshly auto-provisioned
            # (and therefore still-paused-by-default) Airflow instance. A
            # quality-test run should just work regardless of the DAG's
            # pause state, so we unpause it ourselves before triggering.
            self.set_dag_paused(dag_id, False)
            dag_run_id = self.trigger_dag_run(dag_id, conf=conf)
        except AirflowUnreachableError as exc:
            return AirflowDagRunOutcome(dag_id=dag_id, dag_run_id=None, state="UNREACHABLE", error=str(exc))

        deadline = time.time() + timeout_seconds
        dag_run: dict = {}
        while time.time() < deadline:
            dag_run = self.get_dag_run(dag_id, dag_run_id)
            if dag_run.get("state") in TERMINAL_STATES:
                break
            time.sleep(poll_interval_seconds)

        task_instances = self.list_task_instances(dag_id, dag_run_id)
        tasks = [
            AirflowTaskInstance(
                task_id=ti["task_id"],
                state=ti.get("state") or "no_status",
                duration=ti.get("duration"),
                try_number=ti.get("try_number", 1),
            )
            for ti in task_instances
        ]

        return AirflowDagRunOutcome(
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            state=dag_run.get("state", "unknown"),
            logical_date=dag_run.get("logical_date") or dag_run.get("execution_date"),
            start_date=dag_run.get("start_date"),
            end_date=dag_run.get("end_date"),
            tasks=tasks,
            raw_dag_run_json=json.dumps(dag_run),
            raw_task_instances_json=json.dumps(task_instances),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
