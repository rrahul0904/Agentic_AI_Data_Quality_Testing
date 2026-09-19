#!/usr/bin/env python3
"""Smoke-test governed Cortex Agent analytics and capture parity-ready evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

try:
    from scripts.rga_testbed.result_signature import result_set_signature
except ModuleNotFoundError:
    from result_signature import result_set_signature

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "rga_semantic_contract.yml"
DEFAULT_OUTPUT = ROOT / "artifacts" / "rga_agent_smoke.json"
REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")
ANALYTICAL_TOOL_TYPES = {"system_execute_sql", "cortex_analyst_text_to_sql"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--agent")
    parser.add_argument("--question", action="append")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_contract(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def default_agent(contract: dict[str, Any]) -> str:
    return f"{contract['database']}.AI.RGA_REINSURANCE_AGENT"


def tasks(contract: dict[str, Any], supplied: list[str] | None) -> list[dict[str, str]]:
    if supplied:
        return [
            {"id": f"adhoc_{index:03d}", "question": question}
            for index, question in enumerate(supplied, 1)
        ]
    return [
        {"id": str(item["id"]), "question": str(item["question"])}
        for item in contract.get("verified_queries", [])
    ]


def questions(contract: dict[str, Any], supplied: list[str] | None) -> list[str]:
    return [item["question"] for item in tasks(contract, supplied)]


def connection_kwargs(env: dict[str, str]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise ValueError("Missing Snowflake environment variables: " + ", ".join(missing))
    if not (
        env.get("SNOWFLAKE_PASSWORD")
        or env.get("SNOWFLAKE_TOKEN")
        or env.get("SNOWFLAKE_AUTHENTICATOR")
    ):
        raise ValueError(
            "Snowflake authentication is required via SNOWFLAKE_PASSWORD, "
            "SNOWFLAKE_TOKEN, or SNOWFLAKE_AUTHENTICATOR"
        )
    kwargs: dict[str, Any] = {
        "account": env["SNOWFLAKE_ACCOUNT"],
        "user": env["SNOWFLAKE_USER"],
        "warehouse": env["SNOWFLAKE_WAREHOUSE"],
        "role": env.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        "database": env.get("RGA_SNOWFLAKE_DATABASE", "RGA_SYNTHETIC_TESTBED"),
        "session_parameters": {"QUERY_TAG": "RGA_AGENT_SMOKE"},
    }
    if env.get("SNOWFLAKE_PASSWORD"):
        kwargs["password"] = env["SNOWFLAKE_PASSWORD"]
    if env.get("SNOWFLAKE_TOKEN"):
        kwargs["token"] = env["SNOWFLAKE_TOKEN"]
    if env.get("SNOWFLAKE_AUTHENTICATOR"):
        kwargs["authenticator"] = env["SNOWFLAKE_AUTHENTICATOR"]
    return kwargs


def request_body(question: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": question}],
            }
        ],
        "background": False,
        "stream": False,
    }


def _coerce_response(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("Agent response JSON is not an object")
        return parsed
    raise ValueError(f"Unsupported Agent response type: {type(value).__name__}")


def _execution_from_payload(
    *,
    name: str | None,
    tool_type: str | None,
    status: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    signature = result_set_signature(payload.get("result_set"))
    return {
        "name": name,
        "type": tool_type,
        "status": status,
        "query_id": payload.get("query_id"),
        "sql": payload.get("sql"),
        "result_signature": signature,
    }


def extract_evidence(response: dict[str, Any]) -> dict[str, Any]:
    texts: list[str] = []
    tool_names: list[str] = []
    tool_types: list[str] = []
    analytical_executions: list[dict[str, Any]] = []

    for item in response.get("content", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            value = item.get("text")
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
            elif isinstance(value, dict) and isinstance(value.get("text"), str):
                texts.append(value["text"].strip())

        tool_use = item.get("tool_use")
        if isinstance(tool_use, dict):
            if tool_use.get("name"):
                tool_names.append(str(tool_use["name"]))
            if tool_use.get("type"):
                tool_types.append(str(tool_use["type"]))

        tool_result = item.get("tool_result")
        if isinstance(tool_result, dict):
            name = str(tool_result.get("name")) if tool_result.get("name") else None
            tool_type = str(tool_result.get("type")) if tool_result.get("type") else None
            if name:
                tool_names.append(name)
            if tool_type:
                tool_types.append(tool_type)
            for content in tool_result.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                payload = content.get("json")
                if isinstance(payload, dict) and (
                    tool_type in ANALYTICAL_TOOL_TYPES
                    or name in ANALYTICAL_TOOL_TYPES
                    or payload.get("result_set") is not None
                ):
                    analytical_executions.append(
                        _execution_from_payload(
                            name=name,
                            tool_type=tool_type,
                            status=tool_result.get("status"),
                            payload=payload,
                        )
                    )

        table = item.get("table")
        if isinstance(table, dict) and isinstance(table.get("result_set"), dict):
            analytical_executions.append(
                _execution_from_payload(
                    name="table",
                    tool_type="table",
                    status="success",
                    payload={
                        "query_id": table.get("query_id"),
                        "result_set": table.get("result_set"),
                    },
                )
            )

    warnings = [
        {"code": item.get("code"), "message": item.get("message")}
        for item in (response.get("warnings") or [])
        if isinstance(item, dict)
    ]
    metadata = response.get("metadata") if isinstance(response.get("metadata"), dict) else {}
    return {
        "role": response.get("role"),
        "text": "\n".join(texts),
        "tool_names": sorted(set(tool_names)),
        "tool_types": sorted(set(tool_types)),
        "analytical_executions": analytical_executions,
        "warnings": warnings,
        "run_id": metadata.get("run_id"),
        "thread_id": response.get("thread_id") or metadata.get("thread_id"),
    }


def assess_evidence(evidence: dict[str, Any]) -> tuple[str, list[str]]:
    errors: list[str] = []
    if evidence.get("role") != "assistant":
        errors.append("response role is not assistant")
    if not evidence.get("text"):
        errors.append("agent returned no final text")
    executions = [
        item
        for item in evidence.get("analytical_executions", [])
        if item.get("status") in (None, "success") and item.get("result_signature")
    ]
    if not executions:
        errors.append("no successful analytical SQL result set was observed")
    if evidence.get("warnings"):
        errors.append("agent returned warnings")
    return ("PASS" if not errors else "FAIL", errors)


def dry_run_payload(agent: str, work: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "status": "DRY_RUN",
        "agent": agent,
        "task_count": len(work),
        "tasks": work,
        "acceptance": [
            "assistant final text is present",
            "successful analytical SQL execution is observed (current system_execute_sql or compatible Analyst result)",
            "analytical result_set is captured as a parity-ready canonical signature",
            "no Agent warnings are returned",
            "reasoning/thinking content is not persisted in evidence",
        ],
    }


def run(agent: str, work: list[dict[str, str]], env: dict[str, str]) -> dict[str, Any]:
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError("snowflake-connector-python is required for live Agent smoke tests") from exc

    connection = snowflake.connector.connect(**connection_kwargs(env))
    results: list[dict[str, Any]] = []
    sql = """
select try_parse_json(
  snowflake.cortex.data_agent_run(%s, %s, true)
) as response
"""
    try:
        cursor = connection.cursor()
        try:
            for task in work:
                body = json.dumps(request_body(task["question"]), separators=(",", ":"))
                cursor.execute(sql, (agent, body))
                wrapper_query_id = getattr(cursor, "sfqid", None)
                row = cursor.fetchone()
                if not row:
                    results.append(
                        {
                            "status": "FAIL",
                            "business_query_id": task["id"],
                            "question": task["question"],
                            "wrapper_query_id": wrapper_query_id,
                            "errors": ["DATA_AGENT_RUN returned no row"],
                        }
                    )
                    continue
                response = _coerce_response(row[0])
                evidence = extract_evidence(response)
                status, errors = assess_evidence(evidence)
                results.append(
                    {
                        "status": status,
                        "business_query_id": task["id"],
                        "question": task["question"],
                        "wrapper_query_id": wrapper_query_id,
                        "errors": errors,
                        **evidence,
                    }
                )
        finally:
            cursor.close()
    finally:
        connection.close()

    failed = sum(item["status"] != "PASS" for item in results)
    return {
        "status": "PASS" if failed == 0 and results else "FAIL",
        "agent": agent,
        "task_count": len(results),
        "passed": len(results) - failed,
        "failed": failed,
        "results": results,
        "evidence_policy": (
            "Final text, tool metadata, SQL/query IDs, result signatures, warnings, and run metadata only; "
            "Agent reasoning is intentionally not persisted."
        ),
    }


def main() -> int:
    args = parse_args()
    contract = load_contract(args.contract)
    agent = args.agent or default_agent(contract)
    work = tasks(contract, args.question)
    if not work:
        print(json.dumps({"status": "FAIL", "error": "No Agent smoke questions configured"}, indent=2))
        return 1
    if args.dry_run:
        print(json.dumps(dry_run_payload(agent, work), indent=2))
        return 0
    if not args.confirm:
        print(json.dumps({"status": "REFUSED", "error": "Refusing live Cortex Agent smoke test without --confirm"}, indent=2))
        return 2
    try:
        report = run(agent, work, dict(os.environ))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "agent": agent}, indent=2))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output), "passed": report["passed"], "failed": report["failed"]}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
