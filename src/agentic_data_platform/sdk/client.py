"""Small dependency-free client for the stable /api/v1 surface."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str]], Any]


def _transport(method: str, url: str, body: dict[str, Any] | None, headers: dict[str, str]) -> Any:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"platform HTTP {exc.code}: {raw[:2000]}") from exc
    except (URLError, OSError) as exc:
        raise RuntimeError(f"platform unavailable: {exc}") from exc


class PlatformClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", *, token: str | None = None, transport: Transport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _transport
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/api/v1/"):
            raise ValueError("SDK only permits stable /api/v1 routes")
        url = f"{self.base_url}{path}"
        if query:
            encoded = urlencode({key: value for key, value in query.items() if value is not None})
            if encoded:
                url += f"?{encoded}"
        return self.transport(method.upper(), url, body, dict(self.headers))

    def get(self, path: str, **query: Any) -> Any:
        return self.request("GET", path, query=query or None)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("POST", path, body=body)

    def health(self) -> Any:
        return self.get("/api/v1/platform/health")

    def inventory(self) -> Any:
        return self.get("/api/v1/platform/inventory")

    def tools(self) -> Any:
        return self.get("/api/v1/tools")

    def domains(self) -> Any:
        return self.get("/api/v1/domains")

    def airflow_inventory(self) -> Any:
        return self.get("/api/v1/airflow/inventory")

    def airflow_assets(self) -> Any:
        return self.get("/api/v1/airflow/assets")

    def dbt_summary(self) -> Any:
        return self.get("/api/v1/dbt/summary")

    def providers(self) -> Any:
        return self.get("/api/v1/providers")

    def skills(self) -> Any:
        return self.get("/api/v1/skills/catalog")

    def invoke_tool(self, name: str, args: dict[str, Any] | None = None, *, actor_mode: str = "analyst", approved: bool = False, dry_run: bool = False) -> Any:
        return self.post(
            f"/api/v1/tools/{name}/invoke",
            {"args": args or {}, "actor_mode": actor_mode, "approved": approved, "dry_run": dry_run},
        )
