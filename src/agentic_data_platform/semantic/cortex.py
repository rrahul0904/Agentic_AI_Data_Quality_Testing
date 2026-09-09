"""Cortex Analyst request planning and live REST adapter."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def build_analyst_request(
    question: str,
    semantic_views: list[str],
    *,
    conversation: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not str(question).strip():
        raise ValueError("question is required")
    if not semantic_views:
        raise ValueError("at least one semantic view is required")
    messages = list(conversation or [])
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": str(question)}],
    })
    return {
        "messages": messages,
        "semantic_models": [
            {"semantic_view": str(view)}
            for view in semantic_views
        ],
    }


class CortexAnalystAdapter:
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

    def run(
        self,
        question: str,
        semantic_views: list[str],
        *,
        conversation: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = build_analyst_request(question, semantic_views, conversation=conversation)
        if not self.available():
            return {
                "status": "SKIP_EXTERNAL",
                "reason": "ADE_SNOWFLAKE_ACCOUNT_URL and ADE_SNOWFLAKE_TOKEN are required for live Cortex Analyst",
                "request": payload,
            }
        request = Request(
            f"{self.account_url}/api/v2/cortex/analyst/message",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                **({"X-Snowflake-Role": self.role} if self.role else {}),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
            return {"status": "PASS", "response": body, "request": payload}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {
                "status": "FAIL",
                "code": exc.code,
                "reason": detail[:4000],
                "request": payload,
            }
        except (URLError, TimeoutError) as exc:
            return {
                "status": "FAIL",
                "reason": f"{type(exc).__name__}: {exc}",
                "request": payload,
            }
