from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import signal
import sqlite3
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _root(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(workspace: str | Path, path: str | Path) -> Path:
    root = _root(workspace)
    candidate = (root / Path(path)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes the governed workspace") from exc
    return candidate


def mode_contract(mode: str, *, budget_usd: float | None = None) -> dict[str, Any]:
    key = str(mode).casefold().replace("-", "_")
    contracts: dict[str, dict[str, Any]] = {
        "agent": {
            "actor_mode": "builder",
            "read_tools": True,
            "workspace_mutations": "approval_required",
            "data_mutations": "approval_required",
            "verification_required": True,
            "recovery_required": True,
            "model_policy": "capability_first",
        },
        "plan": {
            "actor_mode": "plan",
            "read_tools": True,
            "workspace_mutations": False,
            "data_mutations": False,
            "verification_required": True,
            "recovery_required": False,
            "model_policy": "reasoning_first",
        },
        "edit": {
            "actor_mode": "builder",
            "read_tools": True,
            "workspace_mutations": "hash_bound_approval",
            "data_mutations": False,
            "verification_required": True,
            "recovery_required": True,
            "model_policy": "code_edit",
        },
        "code": {
            "actor_mode": "builder",
            "read_tools": True,
            "workspace_mutations": "hash_bound_approval",
            "data_mutations": False,
            "verification_required": True,
            "recovery_required": True,
            "model_policy": "lowest_cost_capable_model",
        },
    }
    if key not in contracts:
        raise ValueError("mode must be agent, plan, edit, or code")
    result = {"status": "PASS", "mode": key, "budget_usd": budget_usd, **contracts[key]}
    result["contract_fingerprint"] = _digest(result)
    return result


def immutable_plan(
    steps: list[dict[str, Any]],
    *,
    environment: str = "dev",
    constraints: dict[str, Any] | None = None,
    verification: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "environment": str(environment).casefold(),
        "steps": steps,
        "constraints": constraints or {},
        "verification": verification or [],
    }
    return {"status": "PASS", **payload, "plan_fingerprint": _digest(payload)}


def verify_immutable_plan(plan: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "environment": plan.get("environment", "dev"),
        "steps": plan.get("steps") or [],
        "constraints": plan.get("constraints") or {},
        "verification": plan.get("verification") or [],
    }
    actual = _digest(payload)
    expected = str(plan.get("plan_fingerprint") or "")
    return {"status": "PASS" if expected == actual else "STALE_PLAN", "expected": expected, "actual": actual}


def plan_file_edit(
    workspace: str | Path,
    path: str,
    content: str,
    *,
    expected_source_hash: str | None = None,
    verification_command: str | list[str] | None = None,
) -> dict[str, Any]:
    target = _path(workspace, path)
    source = target.read_text(encoding="utf-8") if target.exists() else ""
    source_hash = _text_digest(source)
    if expected_source_hash and expected_source_hash != source_hash:
        return {"status": "STALE_SOURCE", "path": str(target), "source_hash": source_hash}
    result_hash = _text_digest(content)
    rel = str(target.relative_to(_root(workspace)))
    payload = {
        "path": rel,
        "source_hash": source_hash,
        "result_hash": result_hash,
        "verification_command": verification_command,
    }
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        "path": rel,
        "source_hash": source_hash,
        "result_hash": result_hash,
        "changed": source_hash != result_hash,
        "verification_command": verification_command,
        "approval_fingerprint": _digest(payload),
        "rollback_required": True,
    }


_BLOCKED_EXECUTABLES = {
    "sudo",
    "su",
    "rm",
    "mkfs",
    "shutdown",
    "reboot",
    "killall",
    "poweroff",
    "halt",
    "fdisk",
}
_BLOCKED_SHELLS = {"bash", "sh", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "powershell", "pwsh", "cmd"}


def _argv(command: str | Iterable[str]) -> list[str]:
    argv = shlex.split(command) if isinstance(command, str) else [str(item) for item in command]
    if not argv:
        raise ValueError("command is required")
    executable = Path(argv[0]).name.casefold()
    if executable in _BLOCKED_EXECUTABLES:
        raise PermissionError(f"blocked executable: {executable}")
    if executable in _BLOCKED_SHELLS:
        raise PermissionError("shell interpreters are blocked; provide an argv-style command")
    return argv


def command_plan(
    workspace: str | Path,
    command: str | Iterable[str],
    *,
    cwd: str = ".",
    timeout_seconds: int = 120,
    max_output_bytes: int = 131072,
    background: bool = False,
) -> dict[str, Any]:
    argv = _argv(command)
    target_cwd = _path(workspace, cwd)
    timeout = max(1, min(int(timeout_seconds), 3600))
    output_cap = max(1024, min(int(max_output_bytes), 2_000_000))
    payload = {
        "argv": argv,
        "cwd": str(target_cwd.relative_to(_root(workspace))),
        "timeout_seconds": timeout,
        "max_output_bytes": output_cap,
        "background": bool(background),
    }
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        **payload,
        "approval_fingerprint": _digest(payload),
        "resource_budget": {"timeout_seconds": timeout, "max_output_bytes": output_cap},
    }


def run_command(
    workspace: str | Path,
    command: str | Iterable[str],
    *,
    cwd: str = ".",
    timeout_seconds: int = 120,
    max_output_bytes: int = 131072,
    background: bool = False,
    approval_fingerprint: str | None = None,
) -> dict[str, Any]:
    plan = command_plan(
        workspace,
        command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        background=background,
    )
    if approval_fingerprint is not None and approval_fingerprint != plan["approval_fingerprint"]:
        return {"status": "STALE_APPROVAL", "approval_fingerprint": plan["approval_fingerprint"]}
    root = _root(workspace)
    target_cwd = _path(root, cwd)
    argv = list(plan["argv"])
    if background:
        shell_dir = root / ".ade" / "shell"
        shell_dir.mkdir(parents=True, exist_ok=True)
        job_id = f"job_{_digest({'argv': argv, 'cwd': str(target_cwd), 'started': time.time()})[:16]}"
        log_path = shell_dir / f"{job_id}.log"
        log_handle = log_path.open("ab")
        proc = subprocess.Popen(
            argv,
            cwd=target_cwd,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log_handle.close()
        record = {
            "job_id": job_id,
            "pid": proc.pid,
            "argv": argv,
            "cwd": str(target_cwd),
            "log_path": str(log_path),
            "started_at": _utc_now(),
            "approval_fingerprint": plan["approval_fingerprint"],
        }
        (shell_dir / f"{job_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return {"status": "RUNNING", **record}
    try:
        completed = subprocess.run(
            argv,
            cwd=target_cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=int(plan["timeout_seconds"]),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "TIMEOUT",
            "returncode": None,
            "stdout": str(exc.stdout or "")[: int(plan["max_output_bytes"])],
            "stderr": str(exc.stderr or "")[: int(plan["max_output_bytes"])],
            "approval_fingerprint": plan["approval_fingerprint"],
        }
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[: int(plan["max_output_bytes"])],
        "stderr": (completed.stderr or "")[: int(plan["max_output_bytes"])],
        "approval_fingerprint": plan["approval_fingerprint"],
    }


def shell_job_status(workspace: str | Path, job_id: str) -> dict[str, Any]:
    record_path = _root(workspace) / ".ade" / "shell" / f"{job_id}.json"
    if not record_path.exists():
        return {"status": "NOT_FOUND", "job_id": job_id}
    record = json.loads(record_path.read_text(encoding="utf-8"))
    pid = int(record["pid"])
    running = True
    try:
        os.kill(pid, 0)
    except OSError:
        running = False
    log_path = Path(record["log_path"])
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return {"status": "RUNNING" if running else "EXITED", **record, "log": log[:131072]}


def shell_job_kill(workspace: str | Path, job_id: str) -> dict[str, Any]:
    status = shell_job_status(workspace, job_id)
    if status["status"] != "RUNNING":
        return status
    try:
        os.killpg(int(status["pid"]), signal.SIGTERM)
    except ProcessLookupError:
        pass
    return {**status, "status": "TERMINATED"}


def apply_file_edit(
    workspace: str | Path,
    path: str,
    content: str,
    *,
    approval_fingerprint: str,
    expected_source_hash: str | None = None,
    verification_command: str | list[str] | None = None,
) -> dict[str, Any]:
    plan = plan_file_edit(
        workspace,
        path,
        content,
        expected_source_hash=expected_source_hash,
        verification_command=verification_command,
    )
    if plan["status"] != "PASS":
        return plan
    if approval_fingerprint != plan["approval_fingerprint"]:
        return {"status": "STALE_APPROVAL", **plan}
    target = _path(workspace, path)
    root = _root(workspace)
    existed = target.exists()
    source = target.read_text(encoding="utf-8") if existed else ""
    rollback = root / ".ade" / "rollback" / plan["approval_fingerprint"] / plan["path"]
    rollback.parent.mkdir(parents=True, exist_ok=True)
    if existed:
        rollback.write_text(source, encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    verification_result = None
    if verification_command:
        verification_result = run_command(root, verification_command)
        if verification_result["status"] != "PASS":
            if existed:
                target.write_text(source, encoding="utf-8")
            elif target.exists():
                target.unlink()
            return {
                "status": "VERIFICATION_FAILED_ROLLED_BACK",
                "path": plan["path"],
                "verification": verification_result,
                "source_hash": plan["source_hash"],
            }
    resulting_hash = _text_digest(target.read_text(encoding="utf-8"))
    return {
        "status": "PASS" if resulting_hash == plan["result_hash"] else "VERIFY_FAILED",
        "path": plan["path"],
        "source_hash": plan["source_hash"],
        "result_hash": resulting_hash,
        "approval_fingerprint": plan["approval_fingerprint"],
        "rollback_path": str(rollback) if existed else None,
        "verification": verification_result,
    }


def select_context(items: list[dict[str, Any]], *, budget_tokens: int = 4000, provider: str = "generic") -> dict[str, Any]:
    budget = max(128, int(budget_tokens))
    ranked: list[tuple[tuple[float, float, float], dict[str, Any], int]] = []
    for item in items:
        text = str(item.get("text") or "")
        estimated = max(1, math.ceil(len(text) / 4))
        evidence = float(item.get("evidence_rank", item.get("evidence_tier", 0)) or 0)
        relevance = float(item.get("relevance", 0) or 0)
        recency = float(item.get("recency", 0) or 0)
        ranked.append(((evidence, relevance, recency), item, estimated))
    ranked.sort(key=lambda row: row[0], reverse=True)
    selected: list[dict[str, Any]] = []
    used = 0
    for _, item, estimated in ranked:
        if used + estimated > budget:
            continue
        selected.append({**item, "estimated_tokens": estimated})
        used += estimated
    return {
        "status": "PASS",
        "provider": provider,
        "budget_tokens": budget,
        "used_tokens": used,
        "selected": selected,
        "omitted_count": len(items) - len(selected),
        "selection_fingerprint": _digest([item.get("id") or item.get("text") for item in selected]),
    }


def validate_agent_definition(definition: dict[str, Any]) -> dict[str, Any]:
    name = str(definition.get("name") or "").strip()
    tools = [str(item) for item in definition.get("allowed_tools") or []]
    scopes = [str(item) for item in definition.get("scopes") or []]
    budgets = dict(definition.get("budgets") or {})
    verification = list(definition.get("verification") or [])
    errors: list[str] = []
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name):
        errors.append("invalid name")
    if not tools:
        errors.append("allowed_tools is required")
    normalized = {
        "name": name,
        "description": str(definition.get("description") or ""),
        "model": str(definition.get("model") or "auto"),
        "allowed_tools": sorted(set(tools)),
        "scopes": sorted(set(scopes)),
        "budgets": budgets,
        "verification": verification,
        "prompt": str(definition.get("prompt") or ""),
    }
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "definition": normalized,
        "definition_fingerprint": _digest(normalized),
        "policy_inheritance": True,
    }


def save_agent_definition(workspace: str | Path, definition: dict[str, Any]) -> dict[str, Any]:
    checked = validate_agent_definition(definition)
    if checked["status"] != "PASS":
        return checked
    path = _root(workspace) / ".ade" / "custom-agents.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing[checked["definition"]["name"]] = checked["definition"]
    path.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "status": "PASS",
        "definition": checked["definition"],
        "definition_fingerprint": checked["definition_fingerprint"],
    }


def list_agent_definitions(workspace: str | Path) -> dict[str, Any]:
    path = _root(workspace) / ".ade" / "custom-agents.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"status": "PASS", "agents": [existing[name] for name in sorted(existing)]}


def search_warehouse_objects(query: str, objects: list[dict[str, Any]], *, limit: int = 20) -> dict[str, Any]:
    terms = {term for term in re.findall(r"[a-z0-9_]+", query.casefold()) if len(term) > 1}
    scored: list[tuple[float, dict[str, Any]]] = []
    for obj in objects:
        haystack = " ".join(
            str(value)
            for value in [
                obj.get("platform"),
                obj.get("database"),
                obj.get("schema"),
                obj.get("name"),
                obj.get("qualified_name"),
                obj.get("description"),
                " ".join(map(str, obj.get("columns") or [])),
            ]
            if value is not None
        ).casefold()
        tokens = set(re.findall(r"[a-z0-9_]+", haystack))
        overlap = len(terms & tokens)
        fuzzy = sum(1 for term in terms if term in haystack)
        lineage_bonus = min(len(obj.get("upstream") or []) + len(obj.get("downstream") or []), 10) * 0.05
        score = overlap * 2.0 + fuzzy + lineage_bonus + (0.25 if obj.get("recent_evidence") else 0.0)
        if score > 0 or not terms:
            scored.append((score, obj))
    scored.sort(key=lambda row: (-row[0], str(row[1].get("qualified_name") or row[1].get("name") or "")))
    return {
        "status": "PASS",
        "query": query,
        "results": [{"score": score, **obj} for score, obj in scored[: max(1, int(limit))]],
        "platforms": sorted({str(obj.get("platform")) for _, obj in scored if obj.get("platform")}),
    }


_READ_ONLY_SQL = re.compile(r"^\s*(select|with|show|describe|desc|explain|pragma)\b", re.I)
_TABLE_REF = re.compile(r"\b(?:from|join)\s+([A-Za-z0-9_.$\"-]+)", re.I)


def sql_playground(
    sql: str,
    *,
    dialect: str = "ansi",
    sqlite_database: str | None = None,
    max_rows: int = 500,
) -> dict[str, Any]:
    statement = str(sql).strip()
    if not _READ_ONLY_SQL.search(statement):
        return {"status": "BLOCKED_POLICY", "reason": "SQL playground is read-only"}
    if ";" in statement.rstrip(";"):
        return {"status": "BLOCKED_POLICY", "reason": "one statement per playground request"}
    tables = sorted(set(_TABLE_REF.findall(statement)))
    result: dict[str, Any] = {
        "status": "PASS",
        "dialect": dialect,
        "query_fingerprint": _text_digest(statement),
        "lineage": {"tables": tables},
        "policy": {"read_only": True, "max_rows": int(max_rows)},
        "optimization": {"review_required": True, "predicate_present": bool(re.search(r"\bwhere\b", statement, re.I))},
        "execution": "NOT_RUN_EXTERNAL",
    }
    if sqlite_database:
        connection = sqlite3.connect(sqlite_database)
        try:
            cursor = connection.execute(statement)
            names = [item[0] for item in cursor.description or []]
            rows = cursor.fetchmany(max(1, int(max_rows)))
            result_rows = [dict(zip(names, row)) for row in rows]
            result.update(
                {
                    "execution": "PASS",
                    "rows": result_rows,
                    "row_count_returned": len(result_rows),
                    "result_fingerprint": _digest(result_rows),
                    "cost_evidence": {"engine": "sqlite", "rows_materialized": len(result_rows)},
                }
            )
        finally:
            connection.close()
    return result


def build_chart_spec(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    x: str,
    y: str,
    source_query: str,
    warehouse: str = "unknown",
    title: str | None = None,
) -> dict[str, Any]:
    if kind not in {"line", "bar", "area", "scatter", "kpi"}:
        raise ValueError("unsupported chart kind")
    if any(x not in row or y not in row for row in rows):
        raise ValueError("x and y columns must exist in every row")
    result_fingerprint = _digest(rows)
    provenance = {
        "warehouse": warehouse,
        "source_query": source_query,
        "query_fingerprint": _text_digest(source_query),
        "result_fingerprint": result_fingerprint,
        "created_at": _utc_now(),
    }
    return {
        "status": "PASS",
        "chart": {"kind": kind, "x": x, "y": y, "title": title, "data": rows},
        "provenance": provenance,
        "replay": {"query": source_query, "warehouse": warehouse, "result_fingerprint": result_fingerprint},
    }


def _linear_fit(values: list[float]) -> tuple[float, float]:
    xs = list(range(len(values)))
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(values)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = (
        sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denominator
        if denominator
        else 0.0
    )
    return y_mean - slope * x_mean, slope


def forecast_series(values: list[float], *, horizon: int = 5) -> dict[str, Any]:
    series = [float(value) for value in values]
    if len(series) < 4:
        raise ValueError("at least four observations are required")
    split = max(3, int(len(series) * 0.8))
    train, holdout = series[:split], series[split:]
    intercept, slope = _linear_fit(train)
    linear_holdout = [intercept + slope * i for i in range(split, len(series))]
    moving_value = statistics.fmean(train[-min(5, len(train)):])
    moving_holdout = [moving_value for _ in holdout]

    def mae(actual: list[float], predicted: list[float]) -> float:
        return statistics.fmean(abs(a - b) for a, b in zip(actual, predicted)) if actual else 0.0

    scores = {
        "linear_trend_mae": mae(holdout, linear_holdout),
        "moving_average_mae": mae(holdout, moving_holdout),
    }
    winner = "linear_trend" if scores["linear_trend_mae"] <= scores["moving_average_mae"] else "moving_average"
    intercept_all, slope_all = _linear_fit(series)
    if winner == "linear_trend":
        forecast = [intercept_all + slope_all * i for i in range(len(series), len(series) + int(horizon))]
    else:
        mean = statistics.fmean(series[-min(5, len(series)):])
        forecast = [mean for _ in range(int(horizon))]
    return {
        "status": "PASS",
        "winner": winner,
        "forecast": forecast,
        "evaluation": scores,
        "series_fingerprint": _digest(series),
        "evaluation_fingerprint": _digest(scores),
    }


def anomaly_compare(values: list[float], *, z_threshold: float = 3.0, mad_threshold: float = 3.5) -> dict[str, Any]:
    series = [float(value) for value in values]
    if len(series) < 3:
        raise ValueError("at least three observations are required")
    mean = statistics.fmean(series)
    stdev = statistics.pstdev(series)
    median = statistics.median(series)
    mad = statistics.median([abs(value - median) for value in series])
    z_flags = [index for index, value in enumerate(series) if stdev and abs((value - mean) / stdev) >= z_threshold]
    mad_flags = [index for index, value in enumerate(series) if mad and abs(0.6745 * (value - median) / mad) >= mad_threshold]
    consensus = sorted(set(z_flags) & set(mad_flags))
    return {
        "status": "PASS",
        "detectors": {"zscore": z_flags, "mad": mad_flags},
        "consensus": consensus,
        "evaluation": {"agreement_count": len(consensus), "union_count": len(set(z_flags) | set(mad_flags))},
        "evidence_fingerprint": _digest({"series": series, "z": z_flags, "mad": mad_flags}),
    }


def document_extract(
    workspace: str | Path,
    path: str,
    *,
    fields: dict[str, str] | None = None,
    chunk_chars: int = 2000,
) -> dict[str, Any]:
    target = _path(workspace, path)
    if not target.exists() or not target.is_file():
        return {"status": "NOT_FOUND", "path": path}
    if target.suffix.casefold() == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return {"status": "SKIP_EXTERNAL", "reason": "install pypdf for local PDF extraction", "path": path}
        reader = PdfReader(str(target))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        text = target.read_text(encoding="utf-8", errors="replace")
    extracted: dict[str, Any] = {}
    for name, pattern in (fields or {}).items():
        match = re.search(pattern, text, re.I | re.M)
        extracted[name] = match.group(1) if match and match.lastindex else match.group(0) if match else None
    size = max(256, min(int(chunk_chars), 10000))
    chunks = [text[index : index + size] for index in range(0, len(text), size)]
    return {
        "status": "PASS",
        "backend": "local",
        "path": str(target.relative_to(_root(workspace))),
        "text_sha256": _text_digest(text),
        "text_length": len(text),
        "fields": extracted,
        "chunks": [{"index": index, "text": chunk, "sha256": _text_digest(chunk)} for index, chunk in enumerate(chunks)],
        "estimated_cost_usd": 0.0,
    }
