#!/usr/bin/env python3
"""Smoke-test the governed RGA Cortex Agent using Snowflake DATA_AGENT_RUN.

Live execution is fail-closed. The evidence deliberately stores final text, tool names,
warnings, query IDs, and run metadata, but not agent reasoning/thinking content.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "rga_semantic_contract.yml"
DEFAULT_OUTPUT = ROOT / "artifacts" / "rga_agent_smoke.json"
REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")


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


def questions(contract: dict[str, Any], supplied: list[str] | None) -> list[str]:
    if supplied:
        return supplied
    return [item["question"] for item in contract.get("verified_queries", [])]


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


def extract_evidence(response: dict[str, Any]) -> dict[str, Any]:
    texts: list[str] = []
    tool_names: list[str] = []
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
        if isinstance(tool_use, dict) and tool_use.get("name"):
            tool_names.append(str(tool_use["name"]))
    warnings = [
        {
            "code": item.get("code"),
            "message": item.get("message"),
        }
        for item in (response.get("warnings") or [])
        if isinstance(item, dict)
    ]
    metadata = response.get("metadata") if isinstance(response.get("metadata"), dict) else {}
    return {
        "role": response.get("role"),
        "text": "\n".join(texts),
        "tool_names": sorted(set(tool_names)),
        "warnings": warnings,
        "run_id": metadata.get("run_id"),
        "thread_id": response.get("thread_id") or metadata.get("thread_id"),
    }


def assess_evidence(evidence: dict[str, Any], required_tool: str = "Reinsurance_Analyst") -> tuple[str, list[str]]:
    errors: list[str] = []
    if evidence.get("role") != "assistant":
        errors.append("response role is not assistant")
    if not evidence.get("text"):
        errors.append("agent returned no final text")
    if required_tool not in evidence.get("tool_names", []):
        errors.append(f"governed tool {required_tool} was not observed")
    if evidence.get("warnings"):
        errors.append("agent returned warnings")
    return ("PASS" if not errors else "FAIL", errors)


def dry_run_payload(agent: str, prompts: list[str]) -> dict[str, Any]:
    return {
        "status": "DRY_RUN",
        "agent": agent,
        "task_count": len(prompts),
        "questions": prompts,
        "acceptance": [
            "assistant final text is present",
            "Reinsurance_Analyst governed tool use is observed",
            "no Agent warnings are returned",
            "reasoning/thinking content is not persisted in evidence",
        ],
    }


def run(agent: str, prompts: list[str], env: dict[str, str]) -> dict[str, Any]:
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
            for prompt in prompts:
                body = json.dumps(request_body(prompt), separators=(",", ":"))
                cursor.execute(sql, (agent, body))
                query_id = getattr(cursor, "sfqid", None)
                row = cursor.fetchone()
                if not row:
                    results.append(
                        {
                            "status": "FAIL",
                            "question": prompt,
                            "query_id": query_id,
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
                        "question": prompt,
                        "query_id": query_id,
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
        "evidence_policy": "Final text/tool/warning/run metadata only; Agent reasoning is intentionally not persisted.",
    }


def main() -> int:
    args = parse_args()
    contract = load_contract(args.contract)
    agent = args.agent or default_agent(contract)
    prompts = questions(contract, args.question)
    if not prompts:
        print(json.dumps({"status": "FAIL", "error": "No Agent smoke questions configured"}, indent=2))
        return 1
    if args.dry_run:
        print(json.dumps(dry_run_payload(agent, prompts), indent=2))
        return 0
    if not args.confirm:
        print(
            json.dumps(
                {
                    "status": "REFUSED",
                    "error": "Refusing live Cortex Agent smoke test without --confirm",
                },
                indent=2,
            )
        )
        return 2
    try:
        report = run(agent, prompts, dict(os.environ))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "agent": agent}, indent=2))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output), "passed": report["passed"], "failed": report["failed"]}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
