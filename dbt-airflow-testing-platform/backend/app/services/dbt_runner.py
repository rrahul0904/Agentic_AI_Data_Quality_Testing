"""Executes dbt against the configured project and parses structured results.

This is the "dbt testing" leg of a Test Run: it shells out to the user's own
dbt installation (dbt-core-mcp style environment awareness -- we never bundle
or fake dbt behavior) and turns run_results.json / manifest.json into rows
the API and UI can render, instead of scraping stdout.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DbtTestRow:
    unique_id: str
    node_kind: str
    name: str
    status: str
    execution_time: float
    message: str | None
    relation_name: str | None


@dataclass
class DbtRunOutcome:
    overall_status: str  # PASSED | FAILED | ERROR
    returncode: int
    command: list[str]
    stdout_tail: str
    rows: list[DbtTestRow] = field(default_factory=list)
    run_results_json: str | None = None
    manifest_excerpt_json: str | None = None


_FAILING_STATUSES = {"fail", "error", "runtime error"}
_RESOURCE_KIND_MAP = {
    "model": "model",
    "test": "test",
    "seed": "seed",
    "snapshot": "snapshot",
}


def parse_run_results(run_results: dict, manifest_nodes: dict) -> tuple[list[DbtTestRow], str]:
    """Shared by the local (`dbt build` subprocess) and dbt Cloud (run
    artifacts fetched over the API) paths, so both report identically
    structured, real per-test rows instead of only a job-level pass/fail."""
    rows: list[DbtTestRow] = []
    any_failure = False
    for result in run_results.get("results", []):
        unique_id = result.get("unique_id", "")
        node = manifest_nodes.get(unique_id, {})
        resource_type = node.get("resource_type", unique_id.split(".")[0] if "." in unique_id else "unknown")
        node_kind = _RESOURCE_KIND_MAP.get(resource_type, resource_type)
        status = str(result.get("status", "unknown")).lower()
        if status in _FAILING_STATUSES:
            any_failure = True

        message = result.get("message")
        if not message and result.get("failures"):
            message = f"{result['failures']} failing row(s)"

        rows.append(
            DbtTestRow(
                unique_id=unique_id,
                node_kind=node_kind,
                name=node.get("name", unique_id),
                status=status,
                execution_time=float(result.get("execution_time", 0.0)),
                message=message,
                relation_name=node.get("relation_name"),
            )
        )

    return rows, ("FAILED" if any_failure else "PASSED")


def run_dbt_build(
    project_dir: str,
    profiles_dir: str,
    target: str = "dev",
    dbt_executable: str = "dbt",
    select: str | None = None,
    timeout_seconds: int = 300,
) -> DbtRunOutcome:
    """Runs `dbt build` (models + seeds + tests) and parses the artifacts it writes.

    dbt build is used instead of `dbt test` alone because a Test Run should
    verify the transformation *and* the tests in one pass, mirroring how the
    Airflow DQ pipeline leg exercises the same project end to end.
    """
    project_path = Path(project_dir)
    target_path = project_path / "target"

    command = [
        dbt_executable,
        "build",
        "--project-dir",
        str(project_path),
        "--profiles-dir",
        profiles_dir,
        "--target",
        target,
        "--no-use-colors",
    ]
    if select:
        command += ["--select", select]

    started = time.time()
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(project_path),
        )
    except FileNotFoundError as exc:
        return DbtRunOutcome(
            overall_status="ERROR",
            returncode=-1,
            command=command,
            stdout_tail=f"dbt executable not found: {exc}",
        )
    except subprocess.TimeoutExpired:
        return DbtRunOutcome(
            overall_status="ERROR",
            returncode=-1,
            command=command,
            stdout_tail=f"dbt build timed out after {timeout_seconds}s",
        )

    elapsed = time.time() - started
    run_results_path = target_path / "run_results.json"
    manifest_path = target_path / "manifest.json"

    if not run_results_path.exists():
        # dbt failed before producing artifacts (e.g. profile/connection error).
        tail = (proc.stdout[-4000:] + "\n" + proc.stderr[-2000:]).strip()
        return DbtRunOutcome(
            overall_status="ERROR",
            returncode=proc.returncode,
            command=command,
            stdout_tail=tail or f"no run_results.json produced in {elapsed:.1f}s",
        )

    run_results = json.loads(run_results_path.read_text())
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"nodes": {}}
    nodes = manifest.get("nodes", {})

    rows, overall_status = parse_run_results(run_results, nodes)

    # Keep the manifest excerpt small: only the nodes we actually reported on.
    manifest_excerpt = {uid: nodes[uid] for uid in (r.unique_id for r in rows) if uid in nodes}

    return DbtRunOutcome(
        overall_status=overall_status,
        returncode=proc.returncode,
        command=command,
        stdout_tail=proc.stdout[-4000:],
        rows=rows,
        run_results_json=json.dumps(run_results),
        manifest_excerpt_json=json.dumps(manifest_excerpt),
    )
