"""Snowflake Cortex Agent administration, threads, runs, and feedback."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def _segment(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Snowflake resource identifier is required")
    return quote(text, safe="")


class CortexAgentClient:
    def __init__(
        self,
        *,
        account_url: str | None = None,
        token: str | None = None,
        role: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.account_url = (account_url or os.getenv("ADE_SNOWFLAKE_ACCOUNT_URL") or "").rstrip("/")
        self.token = token or os.getenv("ADE_SNOWFLAKE_TOKEN")
        self.role = role or os.getenv("ADE_SNOWFLAKE_ROLE")
        self.timeout_seconds = max(1, int(timeout_seconds))

    def available(self) -> bool:
        return bool(self.account_url and self.token)

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        endpoint = f"{self.account_url}{path}" if self.account_url else path
        if query:
            encoded = urlencode({k: v for k, v in query.items() if v is not None})
            endpoint += ("?" if "?" not in endpoint else "&") + encoded
        if not self.available():
            return {
                "status": "SKIP_EXTERNAL",
                "reason": "ADE_SNOWFLAKE_ACCOUNT_URL and ADE_SNOWFLAKE_TOKEN are required for Cortex Agent REST calls",
                "method": method,
                "endpoint": endpoint,
                "request": payload,
            }
        request = Request(
            endpoint,
            method=method,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                **({"X-Snowflake-Role": self.role} if self.role else {}),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                body = json.loads(raw) if raw.strip() else {}
            return {"status": "PASS", "response": body}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"status": "FAIL", "code": exc.code, "reason": detail[:4000]}
        except (URLError, TimeoutError) as exc:
            return {"status": "FAIL", "reason": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def agent_path(database: str, schema: str, name: str | None = None) -> str:
        base = f"/api/v2/databases/{_segment(database)}/schemas/{_segment(schema)}/agents"
        return f"{base}/{_segment(name)}" if name else base

    def plan_create(
        self,
        database: str,
        schema: str,
        specification: dict[str, Any],
        *,
        create_mode: str = "errorIfExists",
    ) -> dict[str, Any]:
        if create_mode not in {"errorIfExists", "orReplace", "ifNotExists"}:
            raise ValueError("create_mode must be errorIfExists, orReplace, or ifNotExists")
        if not str(specification.get("name") or "").strip():
            raise ValueError("agent specification requires name")
        return {
            "status": "PASS",
            "method": "POST",
            "path": self.agent_path(database, schema),
            "query": {"createMode": create_mode},
            "request": specification,
        }

    def create(self, database: str, schema: str, specification: dict[str, Any], *, create_mode: str = "errorIfExists") -> dict[str, Any]:
        plan = self.plan_create(database, schema, specification, create_mode=create_mode)
        return self._request(plan["method"], plan["path"], payload=plan["request"], query=plan["query"])

    def list(self, database: str, schema: str, *, like: str | None = None, limit: int | None = None) -> dict[str, Any]:
        return self._request(
            "GET",
            self.agent_path(database, schema),
            query={"like": like, "limit": limit},
        )

    def describe(self, database: str, schema: str, name: str) -> dict[str, Any]:
        return self._request("GET", self.agent_path(database, schema, name))

    def update(self, database: str, schema: str, name: str, specification: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", self.agent_path(database, schema, name), payload=specification)

    def delete(self, database: str, schema: str, name: str, *, if_exists: bool = True) -> dict[str, Any]:
        return self._request(
            "DELETE",
            self.agent_path(database, schema, name),
            query={"ifExists": str(bool(if_exists)).lower()},
        )

    def create_thread(self, *, origin_application: str = "ade") -> dict[str, Any]:
        if len(origin_application.encode("utf-8")) > 16:
            raise ValueError("origin_application is limited to 16 bytes")
        return self._request("POST", "/api/v2/cortex/threads", payload={"origin_application": origin_application})

    def list_threads(self, *, page_size: int = 50) -> dict[str, Any]:
        return self._request("GET", "/api/v2/cortex/threads", query={"page_size": max(1, min(int(page_size), 1000))})

    def describe_thread(
        self,
        thread_id: int | str,
        *,
        page_size: int = 50,
        last_message_id: int | str | None = None,
        message_type: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v2/cortex/threads/{_segment(str(thread_id))}",
            query={
                "page_size": max(1, min(int(page_size), 1000)),
                "last_message_id": last_message_id,
                "message_type": message_type,
            },
        )

    def update_thread(self, thread_id: int | str, *, thread_name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v2/cortex/threads/{_segment(str(thread_id))}",
            payload={"thread_name": thread_name},
        )

    def delete_thread(self, thread_id: int | str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/v2/cortex/threads/{_segment(str(thread_id))}")

    @staticmethod
    def build_run_request(
        question: str,
        *,
        thread_id: int | str | None = None,
        parent_message_id: int | str = 0,
        tool_names: list[str] | None = None,
        background: bool = False,
        stream: bool = False,
    ) -> dict[str, Any]:
        if not str(question).strip():
            raise ValueError("question is required")
        if background and thread_id is None:
            raise ValueError("background Cortex Agent runs require a thread_id")
        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": str(question)}],
                }
            ],
            "stream": bool(stream),
            "background": bool(background),
        }
        if thread_id is not None:
            payload["thread_id"] = thread_id
            payload["parent_message_id"] = parent_message_id
        if tool_names:
            payload["tool_choice"] = {"type": "required", "name": [str(item) for item in tool_names]}
        return payload

    def run(
        self,
        database: str,
        schema: str,
        name: str,
        question: str,
        *,
        thread_id: int | str | None = None,
        parent_message_id: int | str = 0,
        tool_names: list[str] | None = None,
        background: bool = False,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload = self.build_run_request(
            question,
            thread_id=thread_id,
            parent_message_id=parent_message_id,
            tool_names=tool_names,
            background=background,
            stream=stream,
        )
        return self._request(
            "POST",
            self.agent_path(database, schema, name) + ":run",
            payload=payload,
        )

    def feedback(self, database: str, schema: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            self.agent_path(database, schema, name) + ":feedback",
            payload=payload,
        )
