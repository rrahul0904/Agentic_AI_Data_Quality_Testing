"""Thin wrapper over dbt Cloud's Administrative API v2.

Mirrors airflow_client.py's shape deliberately: trigger a job run, poll it to
a terminal state, read back per-step results -- the same "talk to it like an
external client would" pattern, so a DbtProject in "cloud" execution mode
plugs into the same orchestrator shape as a "local" one and an Airflow leg.

Reference: https://docs.getdbt.com/dbt-cloud/api-v2  (auth header is
`Authorization: Token <api_token>` -- note "Token", not "Bearer").

NOTE: implemented against the documented API surface; not exercised against
a live dbt Cloud account in this environment (no credentials available).
Validate `validate_credentials()` and a real job trigger against your own
account before relying on this for anything important.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

# dbt Cloud run status codes (Administrative API v2)
QUEUED, STARTING, RUNNING = 1, 2, 3
SUCCESS, ERROR, CANCELLED = 10, 20, 30
TERMINAL_STATUSES = {SUCCESS, ERROR, CANCELLED}
_STATUS_NAME = {
    QUEUED: "queued",
    STARTING: "starting",
    RUNNING: "running",
    SUCCESS: "success",
    ERROR: "error",
    CANCELLED: "cancelled",
}


class DbtCloudApiError(RuntimeError):
    pass


@dataclass
class DbtCloudStepResult:
    name: str
    status: str
    logs_tail: str | None = None


@dataclass
class DbtCloudJobRunOutcome:
    job_id: str
    run_id: str | None
    status: str  # queued|starting|running|success|error|cancelled|UNREACHABLE
    steps: list[DbtCloudStepResult] = field(default_factory=list)
    test_rows: list = field(default_factory=list)  # dbt_runner.DbtTestRow, kept untyped here to avoid a circular import
    raw_run_json: str | None = None
    error: str | None = None


class DbtCloudClient:
    def __init__(self, host: str, account_id: str, api_token: str, timeout_seconds: int = 15):
        self.base_url = f"https://{host.rstrip('/')}/api/v2/accounts/{account_id}"
        self.headers = {"Authorization": f"Token {api_token}"}
        self.timeout_seconds = timeout_seconds

    def _get(self, path: str, **kwargs) -> dict:
        resp = requests.get(f"{self.base_url}{path}", headers=self.headers, timeout=self.timeout_seconds, **kwargs)
        if resp.status_code >= 300:
            raise DbtCloudApiError(f"GET {path} failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json()

    def _post(self, path: str, json: dict | None = None) -> dict:
        resp = requests.post(f"{self.base_url}{path}", headers=self.headers, json=json, timeout=self.timeout_seconds)
        if resp.status_code >= 300:
            raise DbtCloudApiError(f"POST {path} failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json()

    def validate_credentials(self) -> None:
        """Raises DbtCloudApiError with a clear message if host/account/token are wrong."""
        self._get("/")

    def list_jobs(self, project_id: str | None = None) -> list[dict]:
        params = {"project_id": project_id} if project_id else {}
        data = self._get("/jobs/", params=params)
        return data.get("data", [])

    def trigger_job_run(self, job_id: str, cause: str = "Triggered by ADE Test Control Tower") -> str:
        data = self._post(f"/jobs/{job_id}/run/", json={"cause": cause})
        return str(data["data"]["id"])

    def get_run(self, run_id: str) -> dict:
        data = self._get(f"/runs/{run_id}/", params={"include_related": '["run_steps"]'})
        return data["data"]

    def get_run_artifact(self, run_id: str, path: str) -> dict | None:
        """dbt Cloud publishes the same run_results.json/manifest.json every
        local `dbt build` writes -- fetching them gives cloud runs the same
        per-test detail as local runs, not just a job-level pass/fail."""
        resp = requests.get(
            f"{self.base_url}/runs/{run_id}/artifacts/{path}", headers=self.headers, timeout=self.timeout_seconds
        )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 300:
            raise DbtCloudApiError(f"get_run_artifact({path}) failed ({resp.status_code}): {resp.text[:500]}")
        return resp.json()

    def run_job_to_completion(
        self,
        job_id: str,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: int = 1800,
    ) -> DbtCloudJobRunOutcome:
        try:
            run_id = self.trigger_job_run(job_id)
        except (DbtCloudApiError, requests.RequestException) as exc:
            return DbtCloudJobRunOutcome(job_id=job_id, run_id=None, status="UNREACHABLE", error=str(exc))

        deadline = time.time() + timeout_seconds
        run: dict = {}
        while time.time() < deadline:
            run = self.get_run(run_id)
            if run.get("status") in TERMINAL_STATUSES:
                break
            time.sleep(poll_interval_seconds)

        steps = [
            DbtCloudStepResult(
                name=step.get("name", f"step {step.get('index')}"),
                status=_STATUS_NAME.get(step.get("status"), str(step.get("status"))),
                logs_tail=(step.get("logs") or "")[-2000:] or None,
            )
            for step in run.get("run_steps", [])
        ]

        test_rows: list = []
        if run.get("status") in (SUCCESS, ERROR):
            try:
                from .dbt_runner import parse_run_results  # local import: avoid a hard import-time cycle

                run_results = self.get_run_artifact(run_id, "run_results.json")
                manifest = self.get_run_artifact(run_id, "manifest.json") if run_results else None
                if run_results:
                    test_rows, _ = parse_run_results(run_results, (manifest or {}).get("nodes", {}))
            except (DbtCloudApiError, requests.RequestException):
                pass  # steps/status are still reported even if artifact fetch fails

        import json as _json

        return DbtCloudJobRunOutcome(
            job_id=job_id,
            run_id=run_id,
            status=_STATUS_NAME.get(run.get("status"), "unknown"),
            steps=steps,
            test_rows=test_rows,
            raw_run_json=_json.dumps(run),
        )
