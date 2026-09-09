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
        return {**plan, "status": "STALE_APPROVAL"}
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
    deviations = [abs(value - median) for value in series]
    mad = statistics.median(deviations)
    # Repeated/flat signals legitimately have MAD=0. Fall back to the median
    # non-zero absolute deviation instead of silently disabling robust detection.
    nonzero_deviations = [value for value in deviations if value > 0]
    robust_scale = mad or (statistics.median(nonzero_deviations) if nonzero_deviations else stdev)
    z_flags = [
        index
        for index, value in enumerate(series)
        if stdev and abs((value - mean) / stdev) >= z_threshold
    ]
    mad_flags = [
        index
        for index, value in enumerate(series)
        if robust_scale and abs(0.6745 * (value - median) / robust_scale) >= mad_threshold
    ]

    # Model-based detector: rolling linear-trend residuals. Each observation is
    # predicted only from prior observations, so the candidate point cannot
    # reduce its own residual by influencing the fitted model.
    residuals: list[tuple[int, float]] = []
    for index in range(3, len(series)):
        intercept, slope = _linear_fit(series[:index])
        predicted = intercept + slope * index
        residuals.append((index, series[index] - predicted))
    absolute_residuals = [abs(residual) for _, residual in residuals]
    residual_baseline = statistics.median(absolute_residuals) if absolute_residuals else 0.0
    nonzero_residuals = [value for value in absolute_residuals if value > 1e-12]
    residual_scale = residual_baseline or (
        statistics.median(nonzero_residuals) if nonzero_residuals else 0.0
    )
    model_threshold = max(residual_scale * 6.0, 1e-9)
    trend_flags = [
        index for index, residual in residuals if abs(residual) >= model_threshold
    ]

    detector_sets = [set(z_flags), set(mad_flags), set(trend_flags)]
    votes = {
        index: sum(index in detector for detector in detector_sets)
        for index in range(len(series))
    }
    consensus = sorted(index for index, count in votes.items() if count >= 2)
    union = set().union(*detector_sets)
    evidence = {
        "series": series,
        "zscore": z_flags,
        "mad": mad_flags,
        "trend_residual": trend_flags,
        "trend_threshold": model_threshold,
    }
    return {
        "status": "PASS",
        "detectors": {
            "zscore": z_flags,
            "mad": mad_flags,
            "trend_residual": trend_flags,
        },
        "detector_types": {
            "zscore": "statistical",
            "mad": "robust_statistical",
            "trend_residual": "model_based",
        },
        "consensus": consensus,
        "evaluation": {
            "agreement_count": len(consensus),
            "union_count": len(union),
            "detector_count": 3,
            "trend_residual_threshold": model_threshold,
        },
        "evidence_fingerprint": _digest(evidence),
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


def _git(workspace: str | Path, args: list[str], *, timeout: int = 120) -> dict[str, Any]:
    root = _root(workspace)
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def git_status(workspace: str | Path) -> dict[str, Any]:
    result = _git(workspace, ["status", "--porcelain=v1", "--branch"])
    return {"status": "PASS" if result["returncode"] == 0 else "FAIL", **result}


def git_change_plan(
    workspace: str | Path,
    operation: str,
    *,
    branch: str | None = None,
    message: str | None = None,
    paths: list[str] | None = None,
    verification_command: str | list[str] | None = None,
) -> dict[str, Any]:
    op = str(operation).casefold()
    if op not in {"branch", "commit"}:
        raise ValueError("operation must be branch or commit")
    if op == "branch" and not branch:
        raise ValueError("branch is required")
    if branch and not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise ValueError("invalid branch name")
    if op == "commit" and not message:
        raise ValueError("commit message is required")
    clean_paths = [
        str(_path(workspace, item).relative_to(_root(workspace)))
        for item in (paths or [])
    ]
    payload = {
        "operation": op,
        "branch": branch,
        "message": message,
        "paths": clean_paths,
        "verification_command": verification_command,
    }
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        **payload,
        "approval_fingerprint": _digest(payload),
        "force_push": False,
        "push": "not_supported_by_design",
    }


def git_change_apply(
    workspace: str | Path,
    operation: str,
    *,
    approval_fingerprint: str,
    branch: str | None = None,
    message: str | None = None,
    paths: list[str] | None = None,
    verification_command: str | list[str] | None = None,
) -> dict[str, Any]:
    plan = git_change_plan(
        workspace,
        operation,
        branch=branch,
        message=message,
        paths=paths,
        verification_command=verification_command,
    )
    if approval_fingerprint != plan["approval_fingerprint"]:
        return {"status": "STALE_APPROVAL", **plan}
    if verification_command:
        verification = run_command(workspace, verification_command)
        if verification["status"] != "PASS":
            return {**plan, "status": "BLOCKED_VERIFICATION", "verification": verification}
    if plan["operation"] == "branch":
        result = _git(workspace, ["switch", "-c", str(plan["branch"])])
    else:
        if not plan["paths"]:
            return {**plan, "status": "FAIL", "reason": "explicit paths are required for commits"}
        staged = _git(workspace, ["add", "--", *plan["paths"]])
        if staged["returncode"] != 0:
            return {"status": "FAIL", "stage": "git-add", **staged}
        result = _git(workspace, ["commit", "-m", str(plan["message"])])
    head = _git(workspace, ["rev-parse", "HEAD"])
    return {
        "status": "PASS" if result["returncode"] == 0 else "FAIL",
        "operation": plan["operation"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "head": head["stdout"] if head["returncode"] == 0 else None,
        "approval_fingerprint": plan["approval_fingerprint"],
    }


def audited_web_fetch(url: str, *, max_bytes: int = 262144, timeout_seconds: int = 15) -> dict[str, Any]:
    import urllib.parse
    import urllib.request

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("only absolute http/https URLs are allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "ADE-Research/1.0"})
    with urllib.request.urlopen(request, timeout=max(1, min(int(timeout_seconds), 60))) as response:  # noqa: S310
        raw = response.read(max(1024, min(int(max_bytes), 2_000_000)) + 1)
        truncated = len(raw) > max_bytes
        raw = raw[:max_bytes]
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
    body = raw.decode("utf-8", errors="replace")
    fingerprint = hashlib.sha256(raw).hexdigest()
    return {
        "status": "PASS",
        "source": {
            "requested_url": url,
            "final_url": final_url,
            "content_type": content_type,
            "retrieved_at": _utc_now(),
        },
        "content": body,
        "content_sha256": fingerprint,
        "truncated": truncated,
        "citation": {"url": final_url, "content_sha256": fingerprint},
    }


def audited_web_search(query: str, *, endpoint_template: str | None = None) -> dict[str, Any]:
    import urllib.parse

    if not endpoint_template:
        return {
            "status": "SKIP_EXTERNAL",
            "query": query,
            "reason": "configure a search endpoint template containing {query}",
            "source_policy": "all returned sources retain URL and retrieval fingerprint",
        }
    if "{query}" not in endpoint_template:
        raise ValueError("endpoint_template must contain {query}")
    url = endpoint_template.replace("{query}", urllib.parse.quote_plus(query))
    evidence = audited_web_fetch(url)
    return {
        "status": evidence["status"],
        "query": query,
        "search_endpoint": url,
        "evidence": evidence,
        "source_policy": "URL + content fingerprint required",
    }


def retrieval_search(
    query: str,
    *,
    documents: list[dict[str, Any]] | None = None,
    backend: str = "local",
    limit: int = 10,
    account_url: str | None = None,
    token: str | None = None,
    service: str | None = None,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    import urllib.parse
    import urllib.request

    key = str(backend).casefold()
    if key == "local":
        terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        ranked: list[tuple[int, dict[str, Any]]] = []
        for doc in documents or []:
            text = str(doc.get("text") or doc.get("content") or "")
            score = len(terms & set(re.findall(r"[a-z0-9_]+", text.casefold())))
            if score:
                ranked.append((score, doc))
        ranked.sort(key=lambda row: -row[0])
        return {
            "status": "PASS",
            "backend": "local",
            "results": [{"score": score, **doc} for score, doc in ranked[: max(1, int(limit))]],
        }
    if key != "cortex_search":
        raise ValueError("backend must be local or cortex_search")
    if not account_url or not token or not service:
        return {
            "status": "SKIP_EXTERNAL",
            "backend": "cortex_search",
            "reason": "account_url, token, and service are required",
        }
    parts = service.split(".")
    if len(parts) != 3:
        raise ValueError("service must be DATABASE.SCHEMA.SERVICE")
    database, schema, name = [urllib.parse.quote(part, safe="") for part in parts]
    endpoint = (
        f"{account_url.rstrip('/')}/api/v2/databases/{database}/schemas/{schema}"
        f"/cortex-search-services/{name}:query"
    )
    payload = json.dumps(
        {"query": query, "columns": columns or [], "limit": int(limit)}
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        body = json.loads(response.read().decode("utf-8"))
    return {
        "status": "PASS",
        "backend": "cortex_search",
        "service": service,
        "results": body.get("results") or body.get("data") or [],
        "evidence_fingerprint": _digest(body),
    }


class EmbeddedAgentSession:
    def __init__(
        self,
        registry: Any,
        *,
        environment: str = "dev",
        actor_mode: str = "builder",
        approval_callback: Any | None = None,
    ) -> None:
        self.registry = registry
        self.environment = environment
        self.actor_mode = actor_mode
        self.approval_callback = approval_callback

    def invoke(self, tool: str, args: dict[str, Any] | None = None, *, run_id: str = "embedded") -> dict[str, Any]:
        from agentic_data_platform.models import ActorMode, Environment, Platform, Risk, ToolRequest
        from agentic_data_platform.tools.registry import ToolInvocation

        definition = self.registry.describe(tool)
        envelope = {
            "tool": tool,
            "risk": definition.risk.value,
            "args_fingerprint": _digest(args or {}),
            "environment": self.environment,
        }
        needs_approval = definition.risk is not Risk.READ_ONLY or definition.requires_approval
        approved = False
        if needs_approval:
            if self.approval_callback is None:
                return {"status": "AWAITING_APPROVAL", "approval": envelope}
            approved = bool(self.approval_callback(envelope))
            if not approved:
                return {"status": "REJECTED", "approval": envelope}
        request = ToolRequest(
            tool=tool,
            operation=tool,
            environment=Environment(self.environment),
            risk=definition.risk,
            args=args or {},
            platform=Platform.LOCAL if Platform.LOCAL in definition.supported_platforms else None,
        )
        return self.registry.invoke(
            ToolInvocation(
                request=request,
                run_id=run_id,
                approved=approved,
                actor_mode=ActorMode(self.actor_mode),
            )
        )


def sdk_contract() -> dict[str, Any]:
    return {
        "status": "PASS",
        "class": "agentic_data_platform.advanced_capabilities.EmbeddedAgentSession",
        "approval_callbacks": "per-tool",
        "backends": ["local", "hosted-runner"],
        "policy": "ToolRegistry inherited",
        "evidence": "run_id + tool result + approval envelope",
    }


def account_admin_plan(sql: str, *, environment: str = "dev") -> dict[str, Any]:
    from agentic_data_platform.snowflake.governed_mutation import plan_snowflake_mutation

    plan = plan_snowflake_mutation(sql, environment=environment)
    return {
        **plan,
        "administration": True,
        "independent_verification_required": True,
        "cross_cloud_extension": "same plan envelope can wrap other warehouse admin adapters",
    }


def gpu_job_plan(
    *,
    backend: str,
    image: str,
    command: str | list[str],
    gpu_count: int = 1,
    max_runtime_seconds: int = 3600,
    hourly_cost_usd: float = 0.0,
    max_cost_usd: float = 25.0,
) -> dict[str, Any]:
    key = str(backend).casefold().replace("-", "_")
    if key not in {"snowflake", "kubernetes", "local_cuda"}:
        raise ValueError("backend must be snowflake, kubernetes, or local_cuda")
    runtime = max(1, int(max_runtime_seconds))
    estimated = max(0.0, float(hourly_cost_usd)) * runtime / 3600 * max(1, int(gpu_count))
    payload = {
        "backend": key,
        "image": image,
        "command": _argv(command),
        "gpu_count": max(1, int(gpu_count)),
        "max_runtime_seconds": runtime,
        "estimated_max_cost_usd": round(estimated, 6),
        "max_cost_usd": float(max_cost_usd),
    }
    blocked = estimated > float(max_cost_usd)
    return {
        "status": "BLOCKED_COST" if blocked else "PASS",
        "mode": "PLAN_ONLY",
        **payload,
        "approval_fingerprint": _digest(payload),
        "portable": True,
    }


def gpu_job_run(workspace: str | Path, plan: dict[str, Any], *, approval_fingerprint: str) -> dict[str, Any]:
    if plan.get("status") != "PASS":
        return {"status": "BLOCKED_POLICY", "reason": "job plan is not executable"}
    if approval_fingerprint != plan.get("approval_fingerprint"):
        return {"status": "STALE_APPROVAL"}
    if plan.get("backend") != "local_cuda":
        return {
            "status": "NOT_RUN_EXTERNAL",
            "backend": plan.get("backend"),
            "reason": "external GPU execution requires the configured backend runner",
            "approval_fingerprint": approval_fingerprint,
        }
    return run_command(
        workspace,
        list(plan["command"]),
        timeout_seconds=int(plan["max_runtime_seconds"]),
    )



def _supervisor(workspace: str | Path):
    from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
    from agentic_data_platform.tools.builtin import build_tool_registry

    root = _root(workspace)
    state = root / ".ade" / "agent-recovery.db"
    state.parent.mkdir(parents=True, exist_ok=True)
    return SupervisorAgent(build_tool_registry(), InvestigationStore(state), root)


def agent_recovery_plan(workspace: str | Path, *, scenario_id: str = "watermark_defect") -> dict[str, Any]:
    supervisor = _supervisor(workspace)
    report = supervisor.investigate(scenario_id)
    public = supervisor.public_report(report.incident_id)
    return {
        "status": "PASS",
        "mode": "LOCAL_PROVING_GROUND",
        "phase": public["state"],
        "incident_id": report.incident_id,
        "external_mutation": False,
        "approval_required": True,
        "first_divergence": public.get("first_divergence"),
        "root_cause": public.get("root_cause"),
        "blast_radius": public.get("blast_radius"),
        "remediation": public.get("remediation"),
        "evidence_count": len(public.get("evidence") or []),
        "agent_result_count": len(public.get("agent_results") or []),
        "execution_boundary": "explicit ToolRegistry approval required before recovery execution",
    }


def agent_recovery_execute(
    workspace: str | Path,
    incident_id: str,
    *,
    approved: bool = False,
    approved_by: str = "ade-toolregistry",
) -> dict[str, Any]:
    if not approved:
        return {
            "status": "AWAITING_APPROVAL",
            "incident_id": incident_id,
            "external_mutation": False,
        }
    supervisor = _supervisor(workspace)
    current = supervisor.get_report(incident_id)
    if not current.approved:
        supervisor.approve(incident_id, approved_by=approved_by)
    resolved = supervisor.execute_approved(incident_id)
    public = supervisor.public_report(resolved.incident_id)
    execution = public.get("execution_result") or {}
    verification = public.get("verification_result") or {}
    return {
        "status": "PASS" if public.get("certification") == "CERTIFIED" else "FAIL",
        "mode": "LOCAL_PROVING_GROUND",
        "incident_id": incident_id,
        "state": public.get("state"),
        "external_mutation": bool(execution.get("external_mutation", False)),
        "airflow_actions": execution.get("airflow_actions") or [],
        "dbt_selector": execution.get("dbt_selector"),
        "dbt_command": execution.get("dbt_command"),
        "verification": verification,
        "certification": public.get("certification"),
        "certifications": public.get("certifications") or [],
        "transitions": public.get("transitions") or [],
    }



def route_model_for_mode(
    mode: str,
    candidates: list[dict[str, Any]],
    *,
    required_capabilities: list[str] | None = None,
    budget_usd: float | None = None,
) -> dict[str, Any]:
    contract = mode_contract(mode, budget_usd=budget_usd)
    required = set(required_capabilities or (["code"] if contract["mode"] == "code" else []))
    eligible: list[dict[str, Any]] = []
    for candidate in candidates:
        capabilities = {str(item) for item in candidate.get("capabilities") or []}
        if not required.issubset(capabilities):
            continue
        estimated_cost = float(
            candidate.get(
                "estimated_cost_usd",
                float(candidate.get("input_cost_usd_per_million", 0.0))
                + float(candidate.get("output_cost_usd_per_million", 0.0)),
            )
        )
        if budget_usd is not None and estimated_cost > float(budget_usd):
            continue
        eligible.append({**candidate, "estimated_cost_usd": estimated_cost})
    if not eligible:
        return {
            "status": "NO_ELIGIBLE_MODEL",
            "mode": contract["mode"],
            "required_capabilities": sorted(required),
            "budget_usd": budget_usd,
        }
    if contract["mode"] == "code":
        eligible.sort(
            key=lambda item: (
                float(item["estimated_cost_usd"]),
                -float(item.get("quality_score", 0.0)),
                str(item.get("name") or ""),
            )
        )
    else:
        eligible.sort(
            key=lambda item: (
                -float(item.get("quality_score", 0.0)),
                float(item["estimated_cost_usd"]),
                str(item.get("name") or ""),
            )
        )
    selected = eligible[0]
    evidence = {
        "mode": contract["mode"],
        "required_capabilities": sorted(required),
        "budget_usd": budget_usd,
        "eligible": [
            {
                "name": item.get("name"),
                "estimated_cost_usd": item["estimated_cost_usd"],
                "quality_score": item.get("quality_score", 0.0),
            }
            for item in eligible
        ],
        "selected": selected.get("name"),
    }
    return {
        "status": "PASS",
        "mode": contract["mode"],
        "policy": contract["model_policy"],
        "selected": selected,
        "eligible_count": len(eligible),
        "routing_evidence": evidence,
        "routing_fingerprint": _digest(evidence),
    }


def _snowflake_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def snowflake_document_extract_plan(
    stage: str,
    document_path: str,
    response_format: dict[str, Any] | list[Any],
    *,
    scores: bool = True,
) -> dict[str, Any]:
    stage_name = str(stage).strip()
    if not re.fullmatch(r"@[A-Za-z0-9_$.-]+", stage_name):
        raise ValueError("stage must be a fully qualified @database.schema.stage identifier")
    if not document_path or document_path.startswith("/") or ".." in Path(document_path).parts:
        raise ValueError("document_path must be a relative stage path")
    response_json = _canonical(response_format)
    sql = (
        "SELECT AI_EXTRACT("
        f"file => TO_FILE({_snowflake_string(stage_name)}, {_snowflake_string(document_path)}), "
        f"responseFormat => PARSE_JSON({_snowflake_string(response_json)}), "
        f"scores => {'TRUE' if scores else 'FALSE'}"
        ") AS extraction"
    )
    evidence = {
        "backend": "snowflake_ai_extract",
        "stage": stage_name,
        "document_path": document_path,
        "response_format": response_format,
        "scores": bool(scores),
        "sql": sql,
    }
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        "backend": "snowflake_ai_extract",
        "read_only": True,
        "sql": sql,
        "query_fingerprint": _text_digest(sql),
        "evidence_fingerprint": _digest(evidence),
        "live": "NOT_RUN_EXTERNAL",
    }


def snowflake_document_parse_plan(
    stage: str,
    document_path: str,
    *,
    mode: str = "LAYOUT",
    page_split: bool = True,
    extract_images: bool = False,
) -> dict[str, Any]:
    stage_name = str(stage).strip()
    if not re.fullmatch(r"@[A-Za-z0-9_$.-]+", stage_name):
        raise ValueError("stage must be a fully qualified @database.schema.stage identifier")
    if not document_path or document_path.startswith("/") or ".." in Path(document_path).parts:
        raise ValueError("document_path must be a relative stage path")
    parse_mode = str(mode).upper()
    if parse_mode not in {"OCR", "LAYOUT"}:
        raise ValueError("mode must be OCR or LAYOUT")
    options = {
        "mode": parse_mode,
        "page_split": bool(page_split),
        "extract_images": bool(extract_images),
    }
    options_sql = (
        "OBJECT_CONSTRUCT("
        + ", ".join(
            [
                "'mode', " + _snowflake_string(parse_mode),
                "'page_split', " + ("TRUE" if page_split else "FALSE"),
                "'extract_images', " + ("TRUE" if extract_images else "FALSE"),
            ]
        )
        + ")"
    )
    sql = (
        "SELECT AI_PARSE_DOCUMENT("
        f"TO_FILE({_snowflake_string(stage_name)}, {_snowflake_string(document_path)}), "
        f"{options_sql}, TRUE"
        ") AS parsed_document"
    )
    return {
        "status": "PASS",
        "mode": "PLAN_ONLY",
        "backend": "snowflake_ai_parse_document",
        "read_only": True,
        "sql": sql,
        "options": options,
        "query_fingerprint": _text_digest(sql),
        "live": "NOT_RUN_EXTERNAL",
    }


def compare_document_extractions(
    local_result: dict[str, Any],
    provider_result: dict[str, Any],
    *,
    expected_fields: dict[str, Any] | None = None,
    provider_cost_usd: float | None = None,
) -> dict[str, Any]:
    local_fields = dict(local_result.get("fields") or {})
    raw_provider_fields = provider_result.get("fields")
    if raw_provider_fields is None:
        raw_provider_fields = (
            provider_result.get("response")
            or (provider_result.get("extraction") or {}).get("response")
            or {}
        )
    provider_fields = dict(raw_provider_fields or {})
    keys = sorted(set(local_fields) | set(provider_fields) | set(expected_fields or {}))

    def normalize(value: Any) -> str:
        return " ".join(str(value).casefold().split()) if value is not None else ""

    comparisons = []
    provider_correct = 0
    local_correct = 0
    for key in keys:
        local_value = local_fields.get(key)
        provider_value = provider_fields.get(key)
        expected = (expected_fields or {}).get(key) if expected_fields is not None else None
        agreement = normalize(local_value) == normalize(provider_value)
        local_match = normalize(local_value) == normalize(expected) if expected_fields is not None else None
        provider_match = normalize(provider_value) == normalize(expected) if expected_fields is not None else None
        if local_match:
            local_correct += 1
        if provider_match:
            provider_correct += 1
        comparisons.append(
            {
                "field": key,
                "local": local_value,
                "provider": provider_value,
                "expected": expected,
                "agreement": agreement,
                "local_matches_expected": local_match,
                "provider_matches_expected": provider_match,
            }
        )
    count = len(keys)
    result = {
        "status": "PASS",
        "fields_compared": count,
        "agreement_rate": (
            sum(1 for item in comparisons if item["agreement"]) / count if count else 1.0
        ),
        "local_accuracy": (
            local_correct / count if expected_fields is not None and count else None
        ),
        "provider_accuracy": (
            provider_correct / count if expected_fields is not None and count else None
        ),
        "cost": {
            "local_usd": float(local_result.get("estimated_cost_usd", 0.0) or 0.0),
            "provider_usd": provider_cost_usd,
        },
        "comparisons": comparisons,
    }
    result["evaluation_fingerprint"] = _digest(result)
    return result
