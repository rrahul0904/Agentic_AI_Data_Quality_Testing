"""Slash-command routing for the production TUI."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Any

from agentic_data_platform.interface import AgenticService


@dataclass(frozen=True)
class CommandSpec:
    name: str
    target: str
    kind: str = "tool"
    text_arg: str | None = None
    description: str = ""


COMMANDS: dict[str, CommandSpec] = {
    "discover": CommandSpec("discover", "platform_discover", description="Scan the current project."),
    "project": CommandSpec("project", "platform_inventory", description="Show project inventory."),
    "connect": CommandSpec("connect", "connection_discover", description="Discover warehouse connections."),
    "providers": CommandSpec("providers", "provider_list", description="List model providers."),
    "models": CommandSpec("models", "provider_models", description="List normalized provider models."),
    "skills": CommandSpec("skills", "skill_catalog", description="List built-in and installed skills."),
    "sql-review": CommandSpec("sql-review", "sql_review", text_arg="sql"),
    "sql-translate": CommandSpec("sql-translate", "sql_translate", text_arg="sql"),
    "query-optimize": CommandSpec("query-optimize", "sql_optimize", text_arg="sql"),
    "data-parity": CommandSpec("data-parity", "data_diff_plan"),
    "pii-audit": CommandSpec("pii-audit", "pii_scan"),
    "cost-report": CommandSpec("cost-report", "finops_report"),
    "lineage-diff": CommandSpec("lineage-diff", "column_lineage_diff"),
    "dbt-develop": CommandSpec("dbt-develop", "dbt_compile", text_arg="selector"),
    "dbt-test": CommandSpec("dbt-test", "dbt_test", text_arg="selector"),
    "dbt-unit-tests": CommandSpec("dbt-unit-tests", "dbt_unit_test_gen", text_arg="model"),
    "dbt-docs": CommandSpec("dbt-docs", "dbt_documentation_gaps"),
    "dbt-analyze": CommandSpec("dbt-analyze", "dbt_incremental_analysis"),
    "dbt-troubleshoot": CommandSpec("dbt-troubleshoot", "dbt_failed_models"),
    "dbt-pr-review": CommandSpec("dbt-pr-review", "dbt_pr_review"),
    "dbt-schema-verify": CommandSpec("dbt-schema-verify", "dbt_validate"),
    "airflow-analyze": CommandSpec("airflow-analyze", "airflow_inventory"),
    "airflow-troubleshoot": CommandSpec("airflow-troubleshoot", "airflow_failure_summary"),
    "root-cause": CommandSpec("root-cause", "platform_root_cause", text_arg="asset"),
    "pipeline-health": CommandSpec("pipeline-health", "airflow_pipeline_health"),
    "train": CommandSpec("train", "training_ingest_text", text_arg="content"),
    "teach": CommandSpec("teach", "training_search", text_arg="query"),
    "training-status": CommandSpec("training-status", "training_status"),
    "trace": CommandSpec("trace", "trace_replay", text_arg="trace_id"),
    "sessions": CommandSpec("sessions", "session_list"),
}


def help_text() -> str:
    names = ["help", *sorted(COMMANDS), "mode", "exit"]
    return "Slash commands:\n" + "\n".join(f"  /{name}" for name in names)


def _args(spec: CommandSpec, tail: str, service: AgenticService) -> dict[str, Any]:
    tail = tail.strip()
    if tail.startswith("{"):
        value = json.loads(tail)
        if not isinstance(value, dict):
            raise ValueError("slash-command JSON arguments must be an object")
        return value
    payload: dict[str, Any] = {}
    if spec.text_arg and tail:
        payload[spec.text_arg] = tail
    if spec.target.startswith(("dbt_", "airflow_", "platform_", "quality_", "finops_", "pii_", "column_", "data_diff")):
        payload.setdefault("project", str(service.project_root))
    if spec.target in {"root-cause", "platform_root_cause"}:
        payload.setdefault("database", str(service.project_root / ".ade" / "quality.db"))
    return payload


def execute(line: str, service: AgenticService) -> dict[str, Any]:
    if not line.startswith("/"):
        raise ValueError("slash command must start with /")
    raw = line[1:].strip()
    if not raw:
        return {"status": "PASS", "text": help_text()}
    parts = shlex.split(raw, posix=True)
    name = parts[0].casefold()
    tail = raw[len(parts[0]):].strip()
    if name == "help":
        return {"status": "PASS", "text": help_text()}
    if name == "exit":
        return {"status": "EXIT"}
    if name == "mode":
        if not tail:
            return {"status": "PASS", "mode": service.actor_mode.value.upper()}
        mode = service.set_mode(tail)
        return {"status": "PASS", "mode": mode.value.upper()}
    try:
        spec = COMMANDS[name]
    except KeyError as exc:
        raise KeyError(f"unknown slash command: /{name}") from exc
    return {
        "status": "PASS",
        "command": name,
        "tool": spec.target,
        "result": service.invoke(spec.target, _args(spec, tail, service)),
    }
