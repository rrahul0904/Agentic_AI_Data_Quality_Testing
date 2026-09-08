"""Idempotent GitHub/GitLab review discovery and end-to-end orchestration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen

from agentic_data_platform.review.dbt import format_review_body, review_dbt_changes
from agentic_data_platform.review.delivery import deliver_github_review
from agentic_data_platform.security.redaction import redact


Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], dict[str, Any]]
_MARKER = "<!-- agentic-data-engineering-review -->"


def _default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={**headers, "Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read().decode(errors="replace")
        try:
            body: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"raw": raw}
        return {"http_status": int(response.status), "body": body}


def _token(token_env: str, provider: str) -> tuple[str | None, dict[str, Any] | None]:
    token = os.getenv(token_env)
    if token:
        return token, None
    return None, {
        "status": "SKIP_EXTERNAL",
        "provider": provider,
        "reason": f"{token_env} is not configured",
    }


def _ok(result: Mapping[str, Any]) -> bool:
    return 200 <= int(result.get("http_status", 0)) < 300


def _body_list(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    body = result.get("body")
    return [dict(item) for item in body] if isinstance(body, list) else []


def discover_github_pull(
    repository: str,
    pull_number: int,
    *,
    token_env: str = "GITHUB_TOKEN",
    api_url: str = "https://api.github.com",
    transport: Transport | None = None,
) -> dict[str, Any]:
    if "/" not in repository:
        raise ValueError("GitHub repository must be owner/name")
    token, skipped = _token(token_env, "github")
    if skipped:
        return skipped
    sender = transport or _default_transport
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "agentic-data-engineering-os",
    }
    root = api_url.rstrip("/") + f"/repos/{repository}/pulls/{int(pull_number)}"
    metadata = sender("GET", root, headers, None)
    files = sender("GET", root + "/files?per_page=100", headers, None)
    if not _ok(metadata) or not _ok(files):
        return {
            "status": "FAIL",
            "provider": "github",
            "stage": "discovery",
            "metadata_http_status": metadata.get("http_status"),
            "files_http_status": files.get("http_status"),
        }
    meta = metadata.get("body") if isinstance(metadata.get("body"), Mapping) else {}
    changed = [str(item.get("filename")) for item in _body_list(files) if item.get("filename")]
    return redact({
        "status": "PASS",
        "provider": "github",
        "repository": repository,
        "pull_number": int(pull_number),
        "title": meta.get("title"),
        "state": meta.get("state"),
        "base_sha": (meta.get("base") or {}).get("sha") if isinstance(meta.get("base"), Mapping) else None,
        "head_sha": (meta.get("head") or {}).get("sha") if isinstance(meta.get("head"), Mapping) else None,
        "changed_files": changed,
    })


def discover_gitlab_merge_request(
    project: str,
    merge_request_iid: int,
    *,
    token_env: str = "GITLAB_TOKEN",
    api_url: str = "https://gitlab.com/api/v4",
    transport: Transport | None = None,
) -> dict[str, Any]:
    token, skipped = _token(token_env, "gitlab")
    if skipped:
        return skipped
    sender = transport or _default_transport
    headers = {"PRIVATE-TOKEN": str(token), "User-Agent": "agentic-data-engineering-os"}
    encoded = quote(project, safe="")
    root = api_url.rstrip("/") + f"/projects/{encoded}/merge_requests/{int(merge_request_iid)}"
    metadata = sender("GET", root, headers, None)
    changes = sender("GET", root + "/changes", headers, None)
    if not _ok(metadata) or not _ok(changes):
        return {
            "status": "FAIL",
            "provider": "gitlab",
            "stage": "discovery",
            "metadata_http_status": metadata.get("http_status"),
            "changes_http_status": changes.get("http_status"),
        }
    meta = metadata.get("body") if isinstance(metadata.get("body"), Mapping) else {}
    change_body = changes.get("body") if isinstance(changes.get("body"), Mapping) else {}
    changed = [
        str(item.get("new_path") or item.get("old_path"))
        for item in (change_body.get("changes") or ())
        if isinstance(item, Mapping) and (item.get("new_path") or item.get("old_path"))
    ]
    return redact({
        "status": "PASS",
        "provider": "gitlab",
        "project": project,
        "merge_request_iid": int(merge_request_iid),
        "title": meta.get("title"),
        "state": meta.get("state"),
        "base_sha": meta.get("diff_refs", {}).get("base_sha") if isinstance(meta.get("diff_refs"), Mapping) else None,
        "head_sha": meta.get("diff_refs", {}).get("head_sha") if isinstance(meta.get("diff_refs"), Mapping) else None,
        "changed_files": sorted(set(changed)),
        "api_url": api_url.rstrip("/"),
    })


def _marked_body(review: Mapping[str, Any]) -> str:
    return format_review_body(review) + "\n\n" + _MARKER


def _same_signature(body: str, signature: str) -> bool:
    return _MARKER in body and f"Signature: {signature}" in body


def sync_github_review_comment(
    review: Mapping[str, Any],
    *,
    repository: str,
    pull_number: int,
    token_env: str = "GITHUB_TOKEN",
    api_url: str = "https://api.github.com",
    transport: Transport | None = None,
) -> dict[str, Any]:
    token, skipped = _token(token_env, "github")
    if skipped:
        return skipped
    sender = transport or _default_transport
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "agentic-data-engineering-os",
    }
    base = api_url.rstrip("/") + f"/repos/{repository}"
    listed = sender("GET", base + f"/issues/{int(pull_number)}/comments?per_page=100", headers, None)
    if not _ok(listed):
        return {"status": "FAIL", "provider": "github", "stage": "comment_discovery", "http_status": listed.get("http_status")}
    signature = str(review.get("signature") or "")
    existing = next((item for item in _body_list(listed) if _MARKER in str(item.get("body") or "")), None)
    if existing and _same_signature(str(existing.get("body") or ""), signature):
        return {"status": "PASS", "provider": "github", "action": "DEDUPED", "comment_id": existing.get("id"), "signature": signature}
    payload = {"body": _marked_body(review)}
    if existing and existing.get("id") is not None:
        result = sender("PATCH", base + f"/issues/comments/{existing['id']}", headers, payload)
        action = "UPDATED"
    else:
        result = sender("POST", base + f"/issues/{int(pull_number)}/comments", headers, payload)
        action = "CREATED"
    return {
        "status": "PASS" if _ok(result) else "FAIL",
        "provider": "github",
        "action": action,
        "signature": signature,
        "http_status": result.get("http_status"),
    }


def sync_gitlab_review_note(
    review: Mapping[str, Any],
    *,
    project: str,
    merge_request_iid: int,
    token_env: str = "GITLAB_TOKEN",
    api_url: str = "https://gitlab.com/api/v4",
    transport: Transport | None = None,
) -> dict[str, Any]:
    token, skipped = _token(token_env, "gitlab")
    if skipped:
        return skipped
    sender = transport or _default_transport
    headers = {"PRIVATE-TOKEN": str(token), "User-Agent": "agentic-data-engineering-os"}
    encoded = quote(project, safe="")
    base = api_url.rstrip("/") + f"/projects/{encoded}/merge_requests/{int(merge_request_iid)}/notes"
    listed = sender("GET", base + "?per_page=100", headers, None)
    if not _ok(listed):
        return {"status": "FAIL", "provider": "gitlab", "stage": "note_discovery", "http_status": listed.get("http_status")}
    signature = str(review.get("signature") or "")
    existing = next((item for item in _body_list(listed) if _MARKER in str(item.get("body") or "")), None)
    if existing and _same_signature(str(existing.get("body") or ""), signature):
        return {"status": "PASS", "provider": "gitlab", "action": "DEDUPED", "note_id": existing.get("id"), "signature": signature}
    payload = {"body": _marked_body(review)}
    if existing and existing.get("id") is not None:
        result = sender("PUT", base + f"/{existing['id']}", headers, payload)
        action = "UPDATED"
    else:
        result = sender("POST", base, headers, payload)
        action = "CREATED"
    return {
        "status": "PASS" if _ok(result) else "FAIL",
        "provider": "gitlab",
        "action": action,
        "signature": signature,
        "http_status": result.get("http_status"),
        "api_url": api_url.rstrip("/"),
    }


def run_github_review_e2e(
    project_dir: str | Path,
    *,
    repository: str,
    pull_number: int,
    target_dir: str | Path | None = None,
    token_env: str = "GITHUB_TOKEN",
    api_url: str = "https://api.github.com",
    dialect: str = "snowflake",
    transport: Transport | None = None,
) -> dict[str, Any]:
    discovery = discover_github_pull(repository, pull_number, token_env=token_env, api_url=api_url, transport=transport)
    if discovery.get("status") != "PASS":
        return discovery
    review = review_dbt_changes(project_dir, target_dir=target_dir, changed_files=discovery["changed_files"], dialect=dialect)
    comment = sync_github_review_comment(review, repository=repository, pull_number=pull_number, token_env=token_env, api_url=api_url, transport=transport)
    if comment.get("status") != "PASS" or comment.get("action") == "DEDUPED":
        return redact({"status": comment.get("status"), "provider": "github", "discovery": discovery, "review": review, "comment": comment, "delivery": {"status": "PASS", "action": "DEDUPED"} if comment.get("action") == "DEDUPED" else None})

    sender = transport or _default_transport
    delivery = deliver_github_review(
        review,
        repository=repository,
        pull_number=pull_number,
        token_env=token_env,
        api_url=api_url,
        sender=lambda method, url, headers, payload: sender(method, url, headers, payload),
    )
    status = "PASS" if delivery.get("status") == "PASS" else "FAIL"
    return redact({"status": status, "provider": "github", "discovery": discovery, "review": review, "comment": comment, "delivery": delivery})


def run_gitlab_review_e2e(
    project_dir: str | Path,
    *,
    project: str,
    merge_request_iid: int,
    target_dir: str | Path | None = None,
    token_env: str = "GITLAB_TOKEN",
    api_url: str = "https://gitlab.com/api/v4",
    dialect: str = "snowflake",
    transport: Transport | None = None,
) -> dict[str, Any]:
    discovery = discover_gitlab_merge_request(project, merge_request_iid, token_env=token_env, api_url=api_url, transport=transport)
    if discovery.get("status") != "PASS":
        return discovery
    review = review_dbt_changes(project_dir, target_dir=target_dir, changed_files=discovery["changed_files"], dialect=dialect)
    delivery = sync_gitlab_review_note(review, project=project, merge_request_iid=merge_request_iid, token_env=token_env, api_url=api_url, transport=transport)
    status = "PASS" if delivery.get("status") == "PASS" else "FAIL"
    return redact({"status": status, "provider": "gitlab", "discovery": discovery, "review": review, "delivery": delivery})
