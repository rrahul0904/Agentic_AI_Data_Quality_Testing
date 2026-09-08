"""Version-aware Airflow REST adapter with injectable transport and guarded mutations."""

from __future__ import annotations

import base64
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str]], dict[str, Any]]


def _http_transport(method: str, url: str, body: dict[str, Any] | None, headers: dict[str, str]) -> dict[str, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - user-configured Airflow endpoint
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"status": response.status}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {"status": "ERROR", "http_status": exc.code, "error": raw[:2000]}
    except (URLError, OSError) as exc:
        return {"status": "ERROR", "error": str(exc)}


class AirflowAdapter:
    """Airflow 3 API-v2 / Airflow 2 API-v1 adapter.

    Live connectivity is optional. Without a base URL methods report SKIP_EXTERNAL.
    Mutations are impossible unless the adapter is constructed with allow_mutation=True;
    production callers additionally pass through ToolRegistry Builder/approval gates.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        version: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        transport: Transport | None = None,
        allow_mutation: bool = False,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.declared_version = version
        self.transport = transport or _http_transport
        self.allow_mutation = allow_mutation
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        elif username is not None and password is not None:
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            self.headers["Authorization"] = f"Basic {encoded}"

    @property
    def api_prefix(self) -> str:
        major = None
        if self.declared_version:
            try:
                major = int(str(self.declared_version).split(".", 1)[0])
            except ValueError:
                major = None
        return "/api/v2" if major is not None and major >= 3 else "/api/v1"

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base_url:
            return {
                "status": "SKIP_EXTERNAL",
                "reason": "Airflow runtime URL is not configured.",
                "method": method,
                "path": path,
            }
        return self.transport(method, f"{self.base_url}{self.api_prefix}{path}", body, dict(self.headers))

    def _mutation(self, method: str, path: str, body: dict[str, Any] | None = None, *, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {"status": "DRY_RUN", "method": method, "path": path, "body": body or {}}
        if not self.allow_mutation:
            raise PermissionError("Airflow mutation requires governed Builder approval")
        return self._request(method, path, body)

    def version(self) -> dict[str, Any]:
        return self._request("GET", "/version")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def dags(self, *, limit: int = 100) -> dict[str, Any]:
        return self._request("GET", f"/dags?limit={max(1, min(limit, 1000))}")

    def dag(self, dag_id: str) -> dict[str, Any]:
        return self._request("GET", f"/dags/{dag_id}")

    def tasks(self, dag_id: str) -> dict[str, Any]:
        return self._request("GET", f"/dags/{dag_id}/tasks")

    def task(self, dag_id: str, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/dags/{dag_id}/tasks/{task_id}")

    def dag_runs(self, dag_id: str, *, limit: int = 100) -> dict[str, Any]:
        return self._request("GET", f"/dags/{dag_id}/dagRuns?limit={max(1, min(limit, 1000))}")

    def dag_run(self, dag_id: str, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/dags/{dag_id}/dagRuns/{run_id}")

    def task_instances(self, dag_id: str, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances")

    def task_instance(self, dag_id: str, run_id: str, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}")

    def logs(self, dag_id: str, run_id: str, task_id: str, *, try_number: int = 1) -> dict[str, Any]:
        return self._request("GET", f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}/logs/{try_number}")

    def variables(self) -> dict[str, Any]:
        return self._request("GET", "/variables")

    def connections(self) -> dict[str, Any]:
        return self._request("GET", "/connections")

    def pools(self) -> dict[str, Any]:
        return self._request("GET", "/pools")

    def assets(self) -> dict[str, Any]:
        path = "/assets" if self.api_prefix == "/api/v2" else "/datasets"
        return self._request("GET", path)

    def asset_events(self) -> dict[str, Any]:
        path = "/assetEvents" if self.api_prefix == "/api/v2" else "/datasets/events"
        return self._request("GET", path)

    def import_errors(self) -> dict[str, Any]:
        return self._request("GET", "/importErrors")

    def trigger(self, dag_id: str, *, conf: dict[str, Any] | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self._mutation("POST", f"/dags/{dag_id}/dagRuns", {"conf": conf or {}}, dry_run=dry_run)

    def pause(self, dag_id: str, *, dry_run: bool = False) -> dict[str, Any]:
        return self._mutation("PATCH", f"/dags/{dag_id}", {"is_paused": True}, dry_run=dry_run)

    def unpause(self, dag_id: str, *, dry_run: bool = False) -> dict[str, Any]:
        return self._mutation("PATCH", f"/dags/{dag_id}", {"is_paused": False}, dry_run=dry_run)

    def clear(self, dag_id: str, *, start_date: str | None = None, end_date: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        body = {"start_date": start_date, "end_date": end_date, "dry_run": dry_run}
        return self._mutation("POST", f"/dags/{dag_id}/clearTaskInstances", body, dry_run=dry_run)

    def backfill(self, dag_id: str, *, start_date: str, end_date: str, dry_run: bool = False) -> dict[str, Any]:
        body = {"dag_id": dag_id, "from_date": start_date, "to_date": end_date}
        path = "/backfills" if self.api_prefix == "/api/v2" else f"/dags/{dag_id}/dagRuns"
        return self._mutation("POST", path, body, dry_run=dry_run)
