#!/usr/bin/env python3
"""Smoke-test a Snowflake-managed MCP server without persisting OAuth tokens or Agent reasoning."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

TOKEN_ENV = "SNOWFLAKE_MCP_ACCESS_TOKEN"
DEFAULT_TIMEOUT = 120


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint")
    parser.add_argument("--account-url")
    parser.add_argument("--database")
    parser.add_argument("--schema")
    parser.add_argument("--server")
    parser.add_argument("--expected-tool", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--token-env", default=TOKEN_ENV)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def build_endpoint(
    *,
    endpoint: str | None,
    account_url: str | None,
    database: str | None,
    schema: str | None,
    server: str | None,
) -> str | None:
    if endpoint:
        value = endpoint.rstrip("/")
        return value if value.startswith("https://") else None
    if not all((account_url, database, schema, server)):
        return None
    account = str(account_url).rstrip("/")
    if not account.startswith("https://"):
        account = "https://" + account
    return (
        f"{account}/api/v2/databases/{quote(str(database), safe='')}"
        f"/schemas/{quote(str(schema), safe='')}"
        f"/mcp-servers/{quote(str(server), safe='')}"
    )


def validate_request(
    *,
    endpoint: str | None,
    expected_tool: str,
    question: str,
    token_env: str,
    env: dict[str, str],
    timeout: int,
    confirm: bool,
    dry_run: bool,
) -> list[str]:
    errors: list[str] = []
    if not endpoint or not endpoint.startswith("https://"):
        errors.append("Snowflake MCP HTTPS endpoint is required")
    if not expected_tool.strip():
        errors.append("expected_tool is required")
    if not question.strip():
        errors.append("question is required")
    if timeout < 1 or timeout > 600:
        errors.append("timeout must be between 1 and 600 seconds")
    if not dry_run:
        if not env.get(token_env):
            errors.append(f"OAuth bearer token is required in {token_env}")
        if not confirm:
            errors.append("Refusing live Snowflake MCP invocation without --confirm")
    return errors


def jsonrpc_request(request_id: int, method: str, params: dict[str, Any] | None = None) -> bytes:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            value = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Snowflake MCP SSE stream contained invalid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Snowflake MCP SSE event must contain a JSON object")
        events.append(value)
    return events


def decode_response(*, content_type: str, body: bytes) -> tuple[list[dict[str, Any]], str]:
    text = body.decode("utf-8", errors="replace")
    if "text/event-stream" in content_type.lower():
        events = parse_sse(text)
        if not events:
            raise RuntimeError("Snowflake MCP SSE response contained no JSON events")
        return events, "sse"
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Snowflake MCP response was neither valid JSON nor SSE") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Snowflake MCP JSON response must be an object")
    return [value], "json"


def _post(
    *,
    endpoint: str,
    token: str,
    payload: bytes,
    timeout: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "governed-semantic-platform-mcp-smoke/1",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            events, transport = decode_response(
                content_type=content_type,
                body=body,
            )
            return {
                "http_status": int(response.status),
                "content_type": content_type,
                "transport": transport,
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "events": events,
                "event_count": len(events),
                "request_id": response.headers.get("x-snowflake-request-id")
                or response.headers.get("x-request-id"),
            }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"Snowflake MCP HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Snowflake MCP connection failed: {exc.reason}") from exc


def _result_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("error") is not None:
            raise RuntimeError(
                "Snowflake MCP JSON-RPC error: " + json.dumps(event["error"], sort_keys=True)
            )
        result = event.get("result")
        if isinstance(result, dict):
            return result
    raise RuntimeError("Snowflake MCP response did not contain a JSON-RPC result")


def tools_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise RuntimeError("Snowflake MCP tools/list result did not contain tools")
    normalized: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "name": str(item.get("name") or ""),
                "title": str(item.get("title") or "") or None,
                "description_sha256": (
                    hashlib.sha256(str(item.get("description") or "").encode()).hexdigest()
                    if item.get("description") is not None
                    else None
                ),
                "input_schema_sha256": (
                    hashlib.sha256(
                        json.dumps(item.get("inputSchema"), sort_keys=True).encode()
                    ).hexdigest()
                    if item.get("inputSchema") is not None
                    else None
                ),
            }
        )
    return normalized


def smoke(
    *,
    endpoint: str,
    token: str,
    expected_tool: str,
    question: str,
    timeout: int,
) -> dict[str, Any]:
    listed = _post(
        endpoint=endpoint,
        token=token,
        payload=jsonrpc_request(1, "tools/list", {}),
        timeout=timeout,
    )
    tools = tools_from_result(_result_payload(listed["events"]))
    names = [item["name"] for item in tools]
    if expected_tool not in names:
        raise RuntimeError(
            f"expected governed MCP tool {expected_tool!r} was not discovered; got {names}"
        )

    called = _post(
        endpoint=endpoint,
        token=token,
        payload=jsonrpc_request(
            2,
            "tools/call",
            {
                "name": expected_tool,
                "arguments": {"message": question},
            },
        ),
        timeout=timeout,
    )
    call_result = _result_payload(called["events"])
    serialized_result = json.dumps(call_result, sort_keys=True, default=str).encode()

    evidence = {
        "status": "PASS",
        "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest(),
        "expected_tool": expected_tool,
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "tools_list": {
            "http_status": listed["http_status"],
            "transport": listed["transport"],
            "content_type": listed["content_type"],
            "response_sha256": listed["response_sha256"],
            "request_id": listed["request_id"],
            "tool_count": len(tools),
            "tools": tools,
        },
        "tools_call": {
            "http_status": called["http_status"],
            "transport": called["transport"],
            "content_type": called["content_type"],
            "response_sha256": called["response_sha256"],
            "request_id": called["request_id"],
            "event_count": called["event_count"],
            "result_sha256": hashlib.sha256(serialized_result).hexdigest(),
            "result_present": bool(call_result),
        },
        "oauth": {
            "token_present": True,
            "token_persisted": False,
        },
        "reasoning_persisted": False,
        "truth_boundary": (
            "This proves an external OAuth-authenticated MCP client discovered and invoked the configured "
            "Snowflake-managed governed tool. Raw tool-call payloads, Agent reasoning traces, and OAuth tokens "
            "are intentionally not persisted. Business-result parity remains certified separately."
        ),
    }
    serialized = json.dumps(evidence, sort_keys=True)
    if token and token in serialized:
        raise RuntimeError("OAuth token leaked into MCP evidence")
    return evidence


def plan(
    *,
    endpoint: str | None,
    expected_tool: str,
    question: str,
    token_env: str,
    timeout: int,
) -> dict[str, Any]:
    return {
        "status": "DRY_RUN",
        "endpoint": endpoint,
        "expected_tool": expected_tool,
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "token_env": token_env,
        "timeout": timeout,
        "requests": [
            {
                "method": "tools/list",
                "accept": "application/json, text/event-stream",
            },
            {
                "method": "tools/call",
                "tool": expected_tool,
                "arguments": ["message"],
                "accept": "application/json, text/event-stream",
            },
        ],
        "evidence_policy": {
            "persist_oauth_token": False,
            "persist_raw_tool_call_result": False,
            "persist_agent_reasoning": False,
            "persist_response_hashes": True,
        },
    }


def main() -> int:
    args = parse_args()
    endpoint = build_endpoint(
        endpoint=args.endpoint,
        account_url=args.account_url,
        database=args.database,
        schema=args.schema,
        server=args.server,
    )
    env = dict(os.environ)
    errors = validate_request(
        endpoint=endpoint,
        expected_tool=args.expected_tool,
        question=args.question,
        token_env=args.token_env,
        env=env,
        timeout=args.timeout,
        confirm=args.confirm,
        dry_run=args.dry_run,
    )
    if errors:
        print(json.dumps({"status": "REFUSED", "errors": errors}, indent=2))
        return 2

    if args.dry_run:
        print(
            json.dumps(
                plan(
                    endpoint=endpoint,
                    expected_tool=args.expected_tool,
                    question=args.question,
                    token_env=args.token_env,
                    timeout=args.timeout,
                ),
                indent=2,
            )
        )
        return 0

    try:
        evidence = smoke(
            endpoint=str(endpoint),
            token=env[args.token_env],
            expected_tool=args.expected_tool,
            question=args.question,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        evidence["output"] = str(args.output)
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
