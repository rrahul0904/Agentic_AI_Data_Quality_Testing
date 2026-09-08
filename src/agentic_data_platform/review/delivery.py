"""External review delivery adapters. Network mutation is separate from review logic."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from agentic_data_platform.review.dbt import format_review_body


Sender = Callable[[str, str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _safe_api_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("review API URL must use http(s) and include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("review API URL must not contain embedded credentials")
    return value.rstrip("/")


def _error_type(http_status: int | None) -> str:
    status = int(http_status or 0)
    if status == 0:
        return "NETWORK_FAILURE"
    if status == 401:
        return "AUTHENTICATION_FAILURE"
    if status == 403:
        return "PERMISSION_FAILURE"
    if status == 429:
        return "RATE_LIMITED"
    if status >= 500:
        return "PROVIDER_OUTAGE"
    return "PROVIDER_ERROR"


def _default_sender(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode(errors="replace")
            try:
                body: Any = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                body = {"raw": raw}
            return {
                "http_status": int(response.status),
                "body": body,
            }
    except HTTPError as exc:
        raw = exc.read().decode(errors="replace") if exc.fp else ""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"raw": raw}
        return {"http_status": int(exc.code), "body": body, "error": str(exc.reason)}
    except (URLError, TimeoutError, OSError) as exc:
        return {"http_status": 0, "body": {}, "error": str(exc)}


def deliver_github_review(
    review: Mapping[str, Any],
    *,
    repository: str,
    pull_number: int,
    token_env: str = "GITHUB_TOKEN",
    api_url: str = "https://api.github.com",
    dry_run: bool = False,
    sender: Sender | None = None,
) -> dict[str, Any]:
    if "/" not in repository:
        raise ValueError("GitHub repository must be owner/name")
    event = {
        "APPROVE": "APPROVE",
        "COMMENT": "COMMENT",
        "REQUEST_CHANGES": "REQUEST_CHANGES",
    }.get(str(review.get("verdict")))
    if event is None:
        raise ValueError(f"unsupported review verdict: {review.get('verdict')}")
    body = format_review_body(review)
    payload = {"body": body, "event": event}
    if dry_run:
        return {
            "status": "DRY_RUN",
            "provider": "github",
            "repository": repository,
            "pull_number": int(pull_number),
            "payload": payload,
        }

    token = os.getenv(token_env)
    if not token:
        return {
            "status": "SKIP_EXTERNAL",
            "provider": "github",
            "reason": f"{token_env} is not configured",
        }
    transport = sender or _default_sender
    result = transport(
        "POST",
        _safe_api_url(api_url)
        + f"/repos/{repository}/pulls/{int(pull_number)}/reviews",
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "agentic-data-engineering-os",
        },
        payload,
    )
    response = {
        "status": "PASS"
        if 200 <= int(result.get("http_status", 0)) < 300
        else "FAIL",
        "provider": "github",
        "repository": repository,
        "pull_number": int(pull_number),
        "verdict": review.get("verdict"),
        "signature": review.get("signature"),
        **result,
    }
    if response["status"] == "FAIL":
        response["error_type"] = _error_type(result.get("http_status"))
    return response
    if response["status"] == "FAIL":
        response["error_type"] = _error_type(result.get("http_status"))
    return response


def deliver_gitlab_review(
    review: Mapping[str, Any],
    *,
    project: str,
    merge_request_iid: int,
    token_env: str = "GITLAB_TOKEN",
    api_url: str = "https://gitlab.com/api/v4",
    dry_run: bool = False,
    sender: Sender | None = None,
) -> dict[str, Any]:
    body = format_review_body(review)
    payload = {"body": body}
    if dry_run:
        return {
            "status": "DRY_RUN",
            "provider": "gitlab",
            "project": project,
            "merge_request_iid": int(merge_request_iid),
            "payload": payload,
        }

    token = os.getenv(token_env)
    if not token:
        return {
            "status": "SKIP_EXTERNAL",
            "provider": "gitlab",
            "reason": f"{token_env} is not configured",
        }
    transport = sender or _default_sender
    encoded = quote(project, safe="")
    result = transport(
        "POST",
        _safe_api_url(api_url)
        + f"/projects/{encoded}/merge_requests/{int(merge_request_iid)}/notes",
        {
            "PRIVATE-TOKEN": token,
            "User-Agent": "agentic-data-engineering-os",
        },
        payload,
    )
    response = {
        "status": "PASS"
        if 200 <= int(result.get("http_status", 0)) < 300
        else "FAIL",
        "provider": "gitlab",
        "project": project,
        "merge_request_iid": int(merge_request_iid),
        "verdict": review.get("verdict"),
        "signature": review.get("signature"),
        **result,
    }
