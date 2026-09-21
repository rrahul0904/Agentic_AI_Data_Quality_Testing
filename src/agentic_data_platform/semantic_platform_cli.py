"""Operator CLI for the governed Snowflake semantic platform.

The platform's basis is:
1. define business semantics once in a canonical contract;
2. compile Snowflake/AI/BI artifacts from that contract;
3. certify semantic parity and release risk;
4. optimize physical execution without changing business meaning.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts" / "rga_testbed"
DEFAULT_CONTRACT = REPO_ROOT / "config" / "rga_semantic_contract.yml"
DEFAULT_DOMAIN = REPO_ROOT / "config" / "rga_domain.yml"
DEFAULT_WORKSPACE = REPO_ROOT / "artifacts" / "semantic_platform_demo"

PRODUCT_BASIS = {
    "problem": "Business logic drifts when Snowflake, Power BI, Excel, and AI define metrics independently.",
    "principle": "Define business semantics once; compile and certify every consumer from the same governed contract.",
    "runtime": "Snowflake Semantic Views are the governed semantic runtime.",
    "consumers": ["Snowflake SQL", "Power BI", "Excel", "Cortex Agent/MCP"],
    "testbed": "Synthetic Life & Health reinsurance data is a repeatable enterprise-scale validation workload, not the product.",
    "performance": (
        "Semantic correctness is independent from physical acceleration. "
        "Materializations, aggregates, Dynamic Tables, clustering, Search Optimization, QAS, and warehouse strategy "
        "may change execution but must not redefine metrics."
    ),
}


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def _script(name: str) -> Path:
    path = SCRIPTS / name
    if not path.exists():
        raise FileNotFoundError(f"required platform script not found: {path}")
    return path


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(cwd or REPO_ROOT),
        env=env,
        check=False,
        text=True,
        capture_output=capture,
    )


def _run_checked(command: Sequence[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    result = _run(command, cwd=cwd, env=env, capture=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return {
        "command": list(command),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _python_script(name: str, *args: str) -> list[str]:
    return [sys.executable, str(_script(name)), *args]


def _snowflake_auth_present(env: dict[str, str]) -> bool:
    return bool(
        env.get("SNOWFLAKE_PASSWORD")
        or env.get("SNOWFLAKE_TOKEN")
        or env.get("SNOWFLAKE_AUTHENTICATOR")
    )


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, AttributeError):
        return False


def readiness_status(
    *,
    env: dict[str, str] | None = None,
    repo_root: Path = REPO_ROOT,
    release_dir: Path | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    release_dir = release_dir or (repo_root / "rga-snowflake-data-platform" / "release")
    required_snowflake = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE")
    missing_snowflake = [name for name in required_snowflake if not env.get(name)]
    if not _snowflake_auth_present(env):
        missing_snowflake.append("SNOWFLAKE_PASSWORD|SNOWFLAKE_TOKEN|SNOWFLAKE_AUTHENTICATOR")

    tools = {
        "python": sys.executable,
        "dbt": shutil.which("dbt"),
        "git": shutil.which("git"),
    }
    dependencies = {
        "yaml": _has_module("yaml"),
        "snowflake_connector": _has_module("snowflake.connector"),
    }
    local = {
        "contract": (repo_root / "config" / "rga_semantic_contract.yml").exists(),
        "domain_contract": (repo_root / "config" / "rga_domain.yml").exists(),
        "release_manifest": (release_dir / "release_manifest.json").exists(),
        "rga_ci_workflow": (repo_root / ".github" / "workflows" / "rga-synthetic-data.yml").exists(),
    }
    snowflake_ready = not missing_snowflake and dependencies["snowflake_connector"]
    dbt_auth_ready = bool(env.get("SNOWFLAKE_PASSWORD"))
    dbt_live_ready = bool(snowflake_ready and tools["dbt"] and dbt_auth_ready)
    xmla_endpoint = env.get("RGA_XMLA_ENDPOINT") or env.get("SNOWFLAKE_XMLA_ENDPOINT")
    return {
        "status": "READY_FOR_LOCAL_BUILD" if all((local["contract"], local["domain_contract"], dependencies["yaml"])) else "BLOCKED",
        "local": local,
        "tools": tools,
        "dependencies": dependencies,
        "external": {
            "snowflake_live_ready": bool(snowflake_ready),
            "snowflake_missing": missing_snowflake,
            "dbt_live_ready": dbt_live_ready,
            "dbt_auth_note": "Generated dbt profile is currently certified for password-based Snowflake authentication.",
            "xmla_endpoint_configured": bool(xmla_endpoint),
            "xmla_endpoint": xmla_endpoint,
            "power_bi_excel_live_parity_ready": bool(xmla_endpoint and snowflake_ready),
        },
        "boundaries": {
            "repository_build": "available",
            "snowflake_live": "available" if snowflake_ready else "credentials_or_connector_required",
            "dbt_live": "available" if dbt_live_ready else "dbt_or_compatible_auth_required",
            "power_bi_excel_live": "available" if xmla_endpoint and snowflake_ready else "feature_gate_or_endpoint_required",
        },
    }


def demo_plan(
    workspace: Path,
    *,
    preset: str = "tiny",
    seed: int = 42,
    policies: int | None = None,
    database: str = "RGA_SYNTHETIC_TESTBED",
    cdc_events_per_type: int = 5,
) -> dict[str, Any]:
    data_dir = workspace / "data"
    cdc_dir = workspace / "cdc"
    sql_dir = workspace / "snowflake"
    dbt_dir = workspace / "dbt"
    release_dir = workspace / "release"
    airflow_dir = workspace / "airflow"
    data_args = [
        "--preset",
        preset,
        "--seed",
        str(seed),
        "--output",
        str(data_dir),
    ]
    if policies is not None:
        data_args += ["--policies", str(policies)]
    commands = [
        _python_script("generate_data.py", *data_args),
        _python_script("validate_dataset.py", "--input", str(data_dir)),
        _python_script(
            "generate_change_events.py",
            "--input",
            str(data_dir),
            "--output",
            str(cdc_dir),
            "--events-per-type",
            str(cdc_events_per_type),
        ),
        _python_script(
            "generate_snowflake_ddl.py",
            "--output",
            str(sql_dir / "001_raw_tables.sql"),
            "--database",
            database,
        ),
        _python_script(
            "generate_load_sql.py",
            "--output",
            str(sql_dir / "002_load_raw.sql"),
            "--database",
            database,
            "--local-root",
            str(data_dir / "csv"),
        ),
        _python_script(
            "generate_cdc_apply_sql.py",
            "--input",
            str(cdc_dir / "change_events.jsonl"),
            "--output",
            str(sql_dir / "003_apply_cdc.sql"),
            "--database",
            database,
        ),
        _python_script("generate_dbt_project.py", "--output", str(dbt_dir)),
        _python_script(
            "build_semantic_release.py",
            "--output",
            str(release_dir),
            "--database",
            database,
        ),
        _python_script("generate_airflow_dag.py", "--output", str(airflow_dir / "rga_synthetic_pipeline.py")),
    ]
    return {
        "workspace": str(workspace),
        "database": database,
        "preset": preset,
        "seed": seed,
        "policies": policies,
        "cdc_events_per_type": cdc_events_per_type,
        "paths": {
            "data": str(data_dir),
            "cdc": str(cdc_dir),
            "snowflake": str(sql_dir),
            "dbt": str(dbt_dir),
            "release": str(release_dir),
            "airflow": str(airflow_dir),
        },
        "commands": commands,
    }


def build_demo(
    workspace: Path,
    *,
    preset: str,
    seed: int,
    policies: int | None,
    database: str,
    cdc_events_per_type: int = 5,
) -> dict[str, Any]:
    plan = demo_plan(
        workspace,
        preset=preset,
        seed=seed,
        policies=policies,
        database=database,
        cdc_events_per_type=cdc_events_per_type,
    )
    workspace.mkdir(parents=True, exist_ok=True)
    steps = []
    for command in plan["commands"]:
        steps.append(_run_checked(command))
    release_manifest = Path(plan["paths"]["release"]) / "release_manifest.json"
    data_manifest = Path(plan["paths"]["data"]) / "manifest.json"
    cdc_manifest = Path(plan["paths"]["cdc"]) / "manifest.json"
    return {
        "status": "PASS",
        "basis": PRODUCT_BASIS,
        "workspace": str(workspace),
        "data_manifest": json.loads(data_manifest.read_text(encoding="utf-8")),
        "cdc_manifest": json.loads(cdc_manifest.read_text(encoding="utf-8")),
        "release_manifest": json.loads(release_manifest.read_text(encoding="utf-8")),
        "steps": [{"command": item["command"], "returncode": item["returncode"]} for item in steps],
        "next": {
            "snowflake_demo": "semantic-platform snowflake-demo --workspace <workspace> --confirm",
            "cdc_apply_sql": "<workspace>/snowflake/003_apply_cdc.sql",
            "benchmark": "semantic-platform benchmark --workspace <workspace> --dry-run",
        },
    }


def _require_confirm(confirm: bool, action: str) -> None:
    if not confirm:
        raise RuntimeError(f"Refusing {action} without --confirm")


def _dbt_profiles(dbt_dir: Path) -> Path:
    example = dbt_dir / "profiles.yml.example"
    target = dbt_dir / "profiles.yml"
    if not example.exists():
        raise FileNotFoundError(f"dbt profile template not found: {example}")
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def scale_test(
    workspace: Path,
    *,
    preset: str,
    policies: int,
    seed: int,
    memory_limit: str,
    parquet: bool = False,
    row_group_size: int = 100000,
) -> dict[str, Any]:
    if policies < 1:
        raise ValueError("policies must be positive")
    data_dir = workspace / "scale-data"
    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    generation_report_path = evidence_dir / "generation_scale.json"

    generation = _run(
        _python_script(
            "benchmark_generation.py",
            "--preset",
            preset,
            "--policies",
            str(policies),
            "--seed",
            str(seed),
            "--output",
            str(data_dir),
            "--report",
            str(generation_report_path),
        ),
        capture=True,
    )
    try:
        generation_report = json.loads(generation.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            generation.stdout.strip()
            or generation.stderr.strip()
            or "generation scale benchmark returned invalid output"
        ) from exc
    if generation.returncode != 0 or generation_report.get("status") != "PASS":
        raise RuntimeError(
            generation_report.get("error")
            or generation.stdout.strip()
            or generation.stderr.strip()
        )

    validation = _run(
        _python_script(
            "validate_dataset_duckdb.py",
            "--input",
            str(data_dir),
            "--memory-limit",
            memory_limit,
        ),
        capture=True,
    )
    try:
        validation_report = json.loads(validation.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            validation.stdout.strip()
            or validation.stderr.strip()
            or "DuckDB scale validator returned invalid output"
        ) from exc
    if validation.returncode != 0 or validation_report.get("status") != "PASS":
        raise RuntimeError(
            validation_report.get("error")
            or json.dumps(validation_report)
        )

    parquet_report = None
    parquet_dir = workspace / "parquet"
    if parquet:
        parquet_result = _run(
            _python_script(
                "materialize_parquet.py",
                "--input",
                str(data_dir),
                "--output",
                str(parquet_dir),
                "--memory-limit",
                memory_limit,
                "--row-group-size",
                str(row_group_size),
            ),
            capture=True,
        )
        try:
            parquet_report = json.loads(parquet_result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                parquet_result.stdout.strip()
                or parquet_result.stderr.strip()
                or "Parquet materialization returned invalid output"
            ) from exc
        if (
            parquet_result.returncode != 0
            or parquet_report.get("status") != "PASS"
        ):
            raise RuntimeError(
                parquet_report.get("error")
                or json.dumps(parquet_report)
            )

    report = {
        "status": "PASS",
        "workspace": str(workspace),
        "data": str(data_dir),
        "preset": preset,
        "policies": policies,
        "seed": seed,
        "memory_limit": memory_limit,
        "generation": generation_report,
        "validation": validation_report,
        "parquet": parquet_report,
        "truth_boundary": (
            "This certifies local streaming generation and out-of-core relational "
            "validation at the executed policy count only. It does not certify "
            "100M policies, Snowflake load scale, warehouse concurrency, or production SLA."
        ),
    }
    report_path = evidence_dir / "scale_test.json"
    report_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    report["report"] = str(report_path)
    return report


def optimize(
    workspace: Path,
    *,
    days: int = 14,
    limit: int = 10000,
    query_tag_prefix: str = "RGA_SEMANTIC_BENCHMARK",
    confirm: bool = False,
    dry_run: bool = False,
    include_query_text: bool = False,
    run_diagnostics: bool = False,
) -> dict[str, Any]:
    manifest = workspace / "release" / "benchmarks" / "manifest.json"
    evidence_dir = workspace / "evidence"
    history_path = evidence_dir / "query_history.json"
    analysis_path = evidence_dir / "workload_analysis.json"
    experiments_path = evidence_dir / "optimization_experiments.sql"
    summary_path = evidence_dir / "optimization_analysis_summary.json"
    reports = sorted(evidence_dir.glob("benchmark-c*-both.json"))
    database = None
    release_manifest = workspace / "release" / "release_manifest.json"
    if release_manifest.exists():
        payload = json.loads(release_manifest.read_text(encoding="utf-8"))
        database = payload.get("database")

    collector_args = [
        "--days",
        str(days),
        "--limit",
        str(limit),
        "--query-tag-prefix",
        query_tag_prefix,
        "--output",
        str(history_path),
    ]
    if database:
        collector_args += ["--database", str(database)]
    if include_query_text:
        collector_args.append("--include-query-text")

    if dry_run:
        collector = _run(
            _python_script(
                "collect_query_history.py",
                *collector_args,
                "--dry-run",
            ),
            capture=True,
        )
        try:
            history_plan = json.loads(collector.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                collector.stdout.strip()
                or collector.stderr.strip()
                or "Query History collector returned invalid dry-run output"
            ) from exc
        if collector.returncode != 0:
            raise RuntimeError(history_plan.get("errors") or collector.stdout.strip())
        return {
            "status": "DRY_RUN",
            "workspace": str(workspace),
            "benchmark_manifest": {
                "path": str(manifest),
                "exists": manifest.exists(),
            },
            "benchmark_reports": [str(path) for path in reports],
            "benchmark_report_count": len(reports),
            "query_history": history_plan,
            "outputs": {
                "history": str(history_path),
                "analysis": str(analysis_path),
                "experiments": str(experiments_path),
                "diagnostics": str(evidence_dir / "optimization_diagnostics.json"),
                "summary": str(summary_path),
            },
            "run_diagnostics": run_diagnostics,
            "policy": (
                "Optimization is evidence-driven. Diagnostics and cost/eligibility estimates "
                "may be generated; physical mutations remain commented out and require "
                "before/after benchmark approval."
            ),
        }

    _require_confirm(confirm, "live Snowflake workload optimization analysis")
    if not manifest.exists():
        raise RuntimeError(
            "benchmark manifest is missing; run semantic-platform demo-build first"
        )
    if not reports:
        raise RuntimeError(
            "benchmark evidence is missing; run semantic-platform certify-live or live benchmark sweeps first"
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)

    collector = _run(
        _python_script(
            "collect_query_history.py",
            *collector_args,
            "--confirm",
        ),
        capture=True,
    )
    if collector.returncode != 0:
        raise RuntimeError(collector.stdout.strip() or collector.stderr.strip())
    collector_summary = json.loads(collector.stdout)

    analysis_args = [
        "--manifest",
        str(manifest),
        "--history",
        str(history_path),
        "--output",
        str(analysis_path),
    ]
    for report in reports:
        analysis_args += ["--report", str(report)]
    analysis_run = _run(
        _python_script("analyze_workload.py", *analysis_args),
        capture=True,
    )
    if analysis_run.returncode != 0:
        raise RuntimeError(
            analysis_run.stdout.strip() or analysis_run.stderr.strip()
        )
    analysis_summary = json.loads(analysis_run.stdout)
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    renderer = _run(
        _python_script(
            "render_optimization_experiments.py",
            "--analysis",
            str(analysis_path),
            "--output",
            str(experiments_path),
        ),
        capture=True,
    )
    if renderer.returncode != 0:
        raise RuntimeError(renderer.stdout.strip() or renderer.stderr.strip())
    renderer_summary = json.loads(renderer.stdout)

    diagnostics_summary = None
    diagnostics_path = evidence_dir / "optimization_diagnostics.json"
    if run_diagnostics:
        diagnostics = _run(
            _python_script(
                "execute_optimization_diagnostics.py",
                "--sql-file",
                str(experiments_path),
                "--output",
                str(diagnostics_path),
                "--confirm",
            ),
            capture=True,
        )
        if diagnostics.returncode != 0:
            raise RuntimeError(
                diagnostics.stdout.strip() or diagnostics.stderr.strip()
            )
        diagnostics_summary = json.loads(diagnostics.stdout)

    report = {
        "status": "PASS",
        "workspace": str(workspace),
        "query_history": collector_summary,
        "benchmark_report_count": len(reports),
        "recommendation_count": int(analysis_summary.get("recommendations", 0)),
        "history_experiment_count": int(
            analysis_summary.get("history_experiments", 0)
        ),
        "experiment_count": int(renderer_summary.get("experiment_count", 0)),
        "executable_physical_mutations": int(
            renderer_summary.get("executable_physical_mutations", 0)
        ),
        "diagnostics": diagnostics_summary,
        "outputs": {
            "history": str(history_path),
            "analysis": str(analysis_path),
            "experiments": str(experiments_path),
            "diagnostics": str(diagnostics_path),
            "summary": str(summary_path),
        },
        "policy": analysis.get("policy"),
        "truth_boundary": (
            "This produces evidence-backed optimization experiments only. It does not "
            "apply clustering, Search Optimization, QAS, Dynamic Tables, materializations, "
            "or warehouse changes automatically."
        ),
    }
    summary_path.write_text(
        json.dumps(report, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    report["report"] = str(summary_path)
    return report


def evaluate_optimization(
    *,
    before_reports: list[Path],
    after_reports: list[Path],
    target_variant: str = "both",
    min_p95_improvement_pct: float = 10.0,
    max_scan_regression_pct: float = 25.0,
    output: Path | None = None,
) -> dict[str, Any]:
    if not before_reports or not after_reports:
        raise ValueError("before_reports and after_reports are required")
    args = [
        "--target-variant",
        target_variant,
        "--min-p95-improvement-pct",
        str(min_p95_improvement_pct),
        "--max-scan-regression-pct",
        str(max_scan_regression_pct),
    ]
    for path in before_reports:
        args += ["--before", str(path)]
    for path in after_reports:
        args += ["--after", str(path)]
    if output:
        args += ["--output", str(output)]

    result = _run(
        _python_script("evaluate_optimization_experiment.py", *args),
        capture=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            result.stdout.strip()
            or result.stderr.strip()
            or "optimization evaluator returned invalid output"
        ) from exc
    if result.returncode not in (0, 3):
        raise RuntimeError(
            payload.get("error")
            or result.stdout.strip()
            or result.stderr.strip()
        )
    return payload


def snowflake_demo(
    workspace: Path,
    *,
    confirm: bool,
    deploy_semantic: bool,
    deploy_ai: bool,
) -> dict[str, Any]:
    _require_confirm(confirm, "live Snowflake demo execution")
    status = readiness_status(release_dir=workspace / "release")
    if not status["external"]["snowflake_live_ready"]:
        raise RuntimeError("Snowflake live execution is not ready: " + ", ".join(status["external"]["snowflake_missing"]))
    if not status["external"]["dbt_live_ready"]:
        raise RuntimeError("dbt live execution is not ready; install dbt and configure password-based Snowflake authentication")

    sql_dir = workspace / "snowflake"
    dbt_dir = workspace / "dbt"
    release = workspace / "release"
    _dbt_profiles(dbt_dir)

    stages: list[dict[str, Any]] = []
    for sql_file in (sql_dir / "001_raw_tables.sql", sql_dir / "002_load_raw.sql"):
        stages.append(
            _run_checked(_python_script("execute_snowflake_sql.py", "--sql-file", str(sql_file), "--confirm"))
        )

    stages.append(
        _run_checked(
            [
                shutil.which("dbt") or "dbt",
                "build",
                "--project-dir",
                str(dbt_dir),
                "--profiles-dir",
                str(dbt_dir),
            ],
            cwd=dbt_dir,
        )
    )

    verify_sql = release / "semantic" / "verify_semantic_view.sql"
    stages.append(
        _run_checked(_python_script("execute_snowflake_sql.py", "--sql-file", str(verify_sql), "--confirm"))
    )

    if deploy_semantic:
        deploy_sql = release / "semantic" / "deploy_semantic_view.sql"
        stages.append(
            _run_checked(_python_script("execute_snowflake_sql.py", "--sql-file", str(deploy_sql), "--confirm"))
        )
        if deploy_ai:
            for sql_file in (release / "ai" / "create_agent.sql", release / "ai" / "create_mcp_server.sql"):
                stages.append(
                    _run_checked(_python_script("execute_snowflake_sql.py", "--sql-file", str(sql_file), "--confirm"))
                )
    elif deploy_ai:
        raise RuntimeError("--deploy-ai requires --deploy-semantic")

    return {
        "status": "PASS",
        "workspace": str(workspace),
        "semantic_deployed": deploy_semantic,
        "ai_deployed": deploy_ai,
        "stages": [{"command": item["command"], "returncode": item["returncode"]} for item in stages],
        "remaining_external": [
            "run live concurrency benchmark",
            "capture Cortex Agent/MCP answer evidence" if deploy_ai else "deploy and verify Cortex Agent/MCP",
            "Power BI/Excel XMLA governed parity",
        ],
    }


def cdc_plan(workspace: Path) -> dict[str, Any]:
    required = {
        "cdc_manifest": workspace / "cdc" / "manifest.json",
        "cdc_events": workspace / "cdc" / "change_events.jsonl",
        "cdc_apply_sql": workspace / "snowflake" / "003_apply_cdc.sql",
        "dbt_project": workspace / "dbt" / "dbt_project.yml",
        "semantic_verify": workspace / "release" / "semantic" / "verify_semantic_view.sql",
    }
    return {
        "workspace": str(workspace),
        "workspace_ready": all(path.exists() for path in required.values()),
        "required_artifacts": {
            name: {"path": str(path), "exists": path.exists()}
            for name, path in required.items()
        },
        "steps": [
            "execute idempotent CDC MERGE SQL",
            "rebuild dbt CORE/MART models",
            "server-verify the governed Semantic View",
            "validate audit ledger and changed RAW rows",
        ],
    }


def apply_cdc(
    workspace: Path,
    *,
    confirm: bool,
    dry_run: bool = False,
    verify_idempotency: bool = False,
) -> dict[str, Any]:
    plan = cdc_plan(workspace)
    if dry_run:
        return {
            "status": "DRY_RUN",
            "verify_idempotency": verify_idempotency,
            **plan,
        }

    _require_confirm(confirm, "live CDC application")
    if not plan["workspace_ready"]:
        missing = [
            name
            for name, value in plan["required_artifacts"].items()
            if not value["exists"]
        ]
        raise RuntimeError(
            "CDC workspace is incomplete; run semantic-platform demo-build first. Missing: "
            + ", ".join(missing)
        )

    status = readiness_status(release_dir=workspace / "release")
    if not status["external"]["snowflake_live_ready"]:
        raise RuntimeError(
            "Snowflake live execution is not ready: "
            + ", ".join(status["external"]["snowflake_missing"])
        )
    if not status["external"]["dbt_live_ready"]:
        raise RuntimeError(
            "dbt live execution is not ready; install dbt and configure password-based Snowflake authentication"
        )

    dbt_dir = workspace / "dbt"
    _dbt_profiles(dbt_dir)
    sql_file = workspace / "snowflake" / "003_apply_cdc.sql"
    events_file = workspace / "cdc" / "change_events.jsonl"
    semantic_verify = workspace / "release" / "semantic" / "verify_semantic_view.sql"
    database = os.environ.get("RGA_SNOWFLAKE_DATABASE", "RGA_SYNTHETIC_TESTBED")
    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    semantic_baseline = evidence_dir / "cdc_semantic_baseline.json"
    stages: list[dict[str, Any]] = []

    baseline_capture = _run(
        _python_script(
            "validate_cdc_semantic_effects.py",
            "--events",
            str(events_file),
            "--database",
            database,
            "--baseline",
            str(semantic_baseline),
            "--mode",
            "capture",
            "--confirm",
        ),
        capture=True,
    )
    try:
        baseline_capture_report = json.loads(baseline_capture.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            baseline_capture.stdout.strip()
            or baseline_capture.stderr.strip()
            or "CDC semantic baseline capture returned invalid output"
        ) from exc
    if baseline_capture.returncode != 0 or baseline_capture_report.get("status") != "PASS":
        raise RuntimeError(
            "CDC semantic baseline capture failed: "
            + (baseline_capture_report.get("error") or json.dumps(baseline_capture_report))
        )

    def execute_apply_cycle(label: str) -> dict[str, Any]:
        stages.append(
            _run_checked(
                _python_script(
                    "execute_snowflake_sql.py",
                    "--sql-file",
                    str(sql_file),
                    "--confirm",
                )
            )
        )
        stages.append(
            _run_checked(
                [
                    shutil.which("dbt") or "dbt",
                    "build",
                    "--project-dir",
                    str(dbt_dir),
                    "--profiles-dir",
                    str(dbt_dir),
                ],
                cwd=dbt_dir,
            )
        )
        stages.append(
            _run_checked(
                _python_script(
                    "execute_snowflake_sql.py",
                    "--sql-file",
                    str(semantic_verify),
                    "--confirm",
                )
            )
        )
        validator = _run(
            _python_script(
                "validate_cdc_application.py",
                "--events",
                str(events_file),
                "--database",
                database,
                "--confirm",
            ),
            capture=True,
        )
        try:
            validation = json.loads(validator.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                validator.stdout.strip()
                or validator.stderr.strip()
                or "CDC validator returned invalid output"
            ) from exc
        if validator.returncode != 0 or validation.get("status") != "PASS":
            raise RuntimeError(
                f"{label} CDC validation failed: "
                + (validation.get("error") or json.dumps(validation))
            )

        semantic_validator = _run(
            _python_script(
                "validate_cdc_semantic_effects.py",
                "--events",
                str(events_file),
                "--database",
                database,
                "--baseline",
                str(semantic_baseline),
                "--mode",
                "validate",
                "--confirm",
            ),
            capture=True,
        )
        try:
            semantic_validation = json.loads(semantic_validator.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                semantic_validator.stdout.strip()
                or semantic_validator.stderr.strip()
                or "CDC semantic-effect validator returned invalid output"
            ) from exc
        if (
            semantic_validator.returncode != 0
            or semantic_validation.get("status") != "PASS"
        ):
            raise RuntimeError(
                f"{label} CDC semantic-effect validation failed: "
                + (
                    semantic_validation.get("error")
                    or json.dumps(semantic_validation)
                )
            )

        return {
            "raw_and_audit": validation,
            "semantic_effects": semantic_validation,
        }

    first_validation = execute_apply_cycle("initial")
    second_validation = None
    if verify_idempotency:
        second_validation = execute_apply_cycle("idempotency")

    cdc_manifest = json.loads(
        (workspace / "cdc" / "manifest.json").read_text(encoding="utf-8")
    )
    report = {
        "status": "PASS",
        "workspace": str(workspace),
        "database": database,
        "verify_idempotency": verify_idempotency,
        "source_event_count": cdc_manifest.get("event_count"),
        "source_scenario_counts": cdc_manifest.get("scenario_counts"),
        "semantic_baseline": str(semantic_baseline),
        "semantic_baseline_capture": baseline_capture_report,
        "validation": first_validation,
        "idempotency_validation": second_validation,
        "stages": [
            {"command": item["command"], "returncode": item["returncode"]}
            for item in stages
        ],
        "semantic_reverified": True,
    }
    evidence_path = workspace / "evidence" / "cdc_application.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report"] = str(evidence_path)
    return report


def benchmark(
    workspace: Path,
    *,
    dry_run: bool,
    confirm_live: bool,
    concurrency: int,
    iterations: int,
    mode: str,
) -> dict[str, Any]:
    manifest = workspace / "release" / "benchmarks" / "manifest.json"
    output = workspace / "evidence" / f"benchmark-c{concurrency}-{mode}.json"
    args = [
        "--manifest",
        str(manifest),
        "--mode",
        mode,
        "--concurrency",
        str(concurrency),
        "--iterations",
        str(iterations),
        "--output",
        str(output),
    ]
    if dry_run:
        args.append("--dry-run")
    if confirm_live:
        args.append("--confirm-live")
    result = _run(_python_script("run_snowflake_benchmark.py", *args), capture=True)
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip())
    payload = json.loads(result.stdout)
    if output.exists():
        payload["report"] = str(output)
    return payload


def parse_concurrency_sweep(value: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError("concurrency sweep must be a comma-separated list of integers") from exc
    if not values:
        raise ValueError("concurrency sweep cannot be empty")
    if any(item < 1 or item > 100 for item in values):
        raise ValueError("every concurrency value must be between 1 and 100")
    return sorted(set(values))


def certification_plan(
    workspace: Path,
    *,
    concurrency: list[int],
    iterations: int,
    deploy_ai: bool,
    apply_cdc_events: bool = False,
    verify_cdc_idempotency: bool = False,
    analyze_optimization: bool = False,
    run_optimization_diagnostics: bool = False,
) -> dict[str, Any]:
    if iterations < 1 or iterations > 100:
        raise ValueError("iterations must be between 1 and 100")
    if verify_cdc_idempotency and not apply_cdc_events:
        raise ValueError("verify_cdc_idempotency requires apply_cdc_events")
    if run_optimization_diagnostics and not analyze_optimization:
        raise ValueError(
            "run_optimization_diagnostics requires analyze_optimization"
        )
    required = {
        "data_manifest": workspace / "data" / "manifest.json",
        "snowflake_ddl": workspace / "snowflake" / "001_raw_tables.sql",
        "snowflake_load": workspace / "snowflake" / "002_load_raw.sql",
        "dbt_project": workspace / "dbt" / "dbt_project.yml",
        "release_manifest": workspace / "release" / "release_manifest.json",
        "semantic_verify": workspace / "release" / "semantic" / "verify_semantic_view.sql",
        "semantic_deploy": workspace / "release" / "semantic" / "deploy_semantic_view.sql",
        "benchmark_manifest": workspace / "release" / "benchmarks" / "manifest.json",
    }
    if deploy_ai:
        required["agent_create"] = workspace / "release" / "ai" / "create_agent.sql"
        required["mcp_create"] = workspace / "release" / "ai" / "create_mcp_server.sql"
    if apply_cdc_events:
        required["cdc_manifest"] = workspace / "cdc" / "manifest.json"
        required["cdc_events"] = workspace / "cdc" / "change_events.jsonl"
        required["cdc_apply_sql"] = workspace / "snowflake" / "003_apply_cdc.sql"
    return {
        "workspace": str(workspace),
        "workspace_ready": all(path.exists() for path in required.values()),
        "required_artifacts": {
            name: {"path": str(path), "exists": path.exists()}
            for name, path in required.items()
        },
        "deployment": {
            "bootstrap_snowflake": True,
            "load_raw": True,
            "dbt_build": True,
            "server_verify_semantic_view": True,
            "deploy_semantic_view": True,
            "deploy_ai": deploy_ai,
            "agent_runtime_smoke": deploy_ai,
            "apply_cdc": apply_cdc_events,
            "verify_cdc_idempotency": verify_cdc_idempotency,
            "analyze_optimization": analyze_optimization,
            "run_optimization_diagnostics": run_optimization_diagnostics,
        },
        "benchmark": {
            "mode": "both",
            "concurrency": concurrency,
            "iterations": iterations,
            "requires_result_parity": True,
            "requires_query_history_telemetry": True,
            "requires_agent_result_parity": deploy_ai,
        },
        "evidence": {
            "directory": str(workspace / "evidence"),
            "workload_analysis": str(workspace / "evidence" / "workload_analysis.json"),
            "query_history": (
                str(workspace / "evidence" / "query_history.json")
                if analyze_optimization
                else None
            ),
            "optimization_summary": (
                str(workspace / "evidence" / "optimization_analysis_summary.json")
                if analyze_optimization
                else None
            ),
            "optimization_experiments": (
                str(workspace / "evidence" / "optimization_experiments.sql")
                if analyze_optimization
                else None
            ),
            "optimization_diagnostics": (
                str(workspace / "evidence" / "optimization_diagnostics.json")
                if run_optimization_diagnostics
                else None
            ),
            "agent_smoke": str(workspace / "evidence" / "agent_smoke.json") if deploy_ai else None,
            "cdc_application": str(workspace / "evidence" / "cdc_application.json") if apply_cdc_events else None,
            "certification_manifest": str(workspace / "evidence" / "certification_manifest.json"),
        },
        "scope": (
            "Snowflake semantic runtime + governed Cortex Agent runtime smoke; "
            "Power BI/Excel XMLA and numerical AI answer parity remain separate."
            if deploy_ai
            else "Snowflake semantic runtime certification; Cortex Agent runtime and Power BI/Excel XMLA remain separate."
        ),
    }


def agent_smoke(
    workspace: Path,
    *,
    confirm: bool,
    dry_run: bool,
    agent: str | None = None,
    questions: list[str] | None = None,
    max_rows: int = 10000,
) -> dict[str, Any]:
    release_manifest_path = workspace / "release" / "release_manifest.json"
    database = "RGA_SYNTHETIC_TESTBED"
    if release_manifest_path.exists():
        release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
        database = release_manifest.get("database") or database
    agent_name = agent or f"{database}.AI.RGA_REINSURANCE_AGENT"
    output = workspace / "evidence" / "agent_smoke.json"
    args = ["--agent", agent_name, "--output", str(output), "--max-rows", str(max_rows)]
    for question in questions or []:
        args += ["--question", question]
    if dry_run:
        args.append("--dry-run")
    elif confirm:
        args.append("--confirm")

    result = _run(_python_script("run_agent_smoke.py", *args), capture=True)
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip())
    payload = json.loads(result.stdout)
    if output.exists() and not dry_run:
        payload = json.loads(output.read_text(encoding="utf-8"))
        payload["report"] = str(output)
    return payload


def agent_benchmark_parity(
    agent_report: dict[str, Any],
    benchmark_report_paths: list[Path],
) -> dict[str, Any]:
    references: dict[str, set[str]] = {}
    for path in benchmark_report_paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        for item in report.get("results", []):
            if item.get("status") != "PASS":
                continue
            query_name = item.get("query_name")
            value_sha = item.get("value_sha256")
            if not query_name or not value_sha:
                continue
            references.setdefault(str(query_name), set()).add(str(value_sha))

    queries: dict[str, Any] = {}
    failed = 0
    for item in agent_report.get("results", []):
        query_id = str(item.get("business_query_id") or "")
        expected = sorted(references.get(query_id, set()))
        observed: list[str] = []
        execution_query_ids: list[str] = []
        for execution in item.get("analytical_executions", []) or []:
            if execution.get("status") not in (None, "success"):
                continue
            signature = execution.get("result_signature")
            if isinstance(signature, dict) and signature.get("value_sha256"):
                observed.append(str(signature["value_sha256"]))
            if execution.get("query_id"):
                execution_query_ids.append(str(execution["query_id"]))
        observed = sorted(set(observed))
        matches = sorted(set(expected) & set(observed))
        if not expected:
            status = "FAIL"
            reason = "canonical benchmark result signature is missing"
        elif not observed:
            status = "FAIL"
            reason = "Agent analytical result signature is missing"
        elif not matches:
            status = "FAIL"
            reason = "Agent analytical result differs from canonical benchmark result"
        else:
            status = "PASS"
            reason = "Agent analytical result matches canonical benchmark values"
        if status != "PASS":
            failed += 1
        queries[query_id] = {
            "status": status,
            "reason": reason,
            "canonical_value_sha256": expected,
            "agent_value_sha256": observed,
            "matched_value_sha256": matches,
            "agent_query_ids": sorted(set(execution_query_ids)),
        }

    return {
        "status": "PASS" if queries and failed == 0 else "FAIL",
        "failed_queries": failed,
        "queries": queries,
        "comparison": "value signature parity; column aliases may differ while row values must remain equivalent",
    }


def certify_live(
    workspace: Path,
    *,
    confirm: bool,
    dry_run: bool,
    concurrency: list[int],
    iterations: int,
    deploy_ai: bool,
    apply_cdc_events: bool = False,
    verify_cdc_idempotency: bool = False,
) -> dict[str, Any]:
    plan = certification_plan(
        workspace,
        concurrency=concurrency,
        iterations=iterations,
        deploy_ai=deploy_ai,
        apply_cdc_events=apply_cdc_events,
        verify_cdc_idempotency=verify_cdc_idempotency,
    )
    if dry_run:
        return {"status": "DRY_RUN", **plan}

    _require_confirm(confirm, "live Snowflake semantic certification")
    if not plan["workspace_ready"]:
        missing = [
            name
            for name, item in plan["required_artifacts"].items()
            if not item["exists"]
        ]
        raise RuntimeError(
            "certification workspace is incomplete; run semantic-platform demo-build first. Missing: "
            + ", ".join(missing)
        )

    deployment = snowflake_demo(
        workspace,
        confirm=True,
        deploy_semantic=True,
        deploy_ai=deploy_ai,
    )

    cdc_application = None
    if apply_cdc_events:
        cdc_application = apply_cdc(
            workspace,
            confirm=True,
            dry_run=False,
            verify_idempotency=verify_cdc_idempotency,
        )

    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    agent_runtime = None
    if deploy_ai:
        agent_runtime = agent_smoke(
            workspace,
            confirm=True,
            dry_run=False,
        )
    benchmark_runs: list[dict[str, Any]] = []
    report_paths: list[Path] = []
    for level in concurrency:
        payload = benchmark(
            workspace,
            dry_run=False,
            confirm_live=True,
            concurrency=level,
            iterations=iterations,
            mode="both",
        )
        report_path = evidence_dir / f"benchmark-c{level}-both.json"
        if not report_path.exists():
            raise RuntimeError(f"benchmark evidence file was not created: {report_path}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_paths.append(report_path)
        benchmark_runs.append(
            {
                "concurrency": level,
                "status": payload.get("status"),
                "result_parity": report.get("result_parity", {}).get("status"),
                "summary": report.get("summary", {}),
                "report": str(report_path),
            }
        )

    agent_answer_parity = None
    agent_parity_output = None
    if deploy_ai and agent_runtime:
        agent_answer_parity = agent_benchmark_parity(agent_runtime, report_paths)
        agent_parity_output = evidence_dir / "agent_result_parity.json"
        agent_parity_output.write_text(json.dumps(agent_answer_parity, indent=2) + "\n", encoding="utf-8")

    workload_output = evidence_dir / "workload_analysis.json"
    workload_args = [
        "--manifest",
        str(workspace / "release" / "benchmarks" / "manifest.json"),
    ]
    for report_path in report_paths:
        workload_args += ["--report", str(report_path)]
    workload_args += ["--output", str(workload_output)]
    _run_checked(_python_script("analyze_workload.py", *workload_args))
    workload = json.loads(workload_output.read_text(encoding="utf-8"))

    all_benchmarks_pass = all(item["status"] == "PASS" for item in benchmark_runs)
    all_parity_pass = all(item["result_parity"] == "PASS" for item in benchmark_runs)
    telemetry_complete = all(
        int(variant.get("telemetry_missing", 0)) == 0
        for item in benchmark_runs
        for variant in item.get("summary", {}).get("variants", {}).values()
    )
    agent_runtime_pass = True if not deploy_ai else bool(agent_runtime and agent_runtime.get("status") == "PASS")
    agent_answer_parity_pass = (
        True
        if not deploy_ai
        else bool(agent_answer_parity and agent_answer_parity.get("status") == "PASS")
    )
    cdc_application_pass = (
        True
        if not apply_cdc_events
        else bool(cdc_application and cdc_application.get("status") == "PASS")
    )
    certification_pass = (
        all_benchmarks_pass
        and all_parity_pass
        and telemetry_complete
        and agent_runtime_pass
        and agent_answer_parity_pass
        and cdc_application_pass
    )

    release_manifest_path = workspace / "release" / "release_manifest.json"
    release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    manifest = {
        "certification_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if certification_pass else "INCOMPLETE",
        "scope": "snowflake_semantic_runtime",
        "workspace": str(workspace),
        "source_sha": release_manifest.get("source_sha"),
        "semantic_manifest_sha256": release_manifest.get("semantic_manifest_sha256"),
        "environment": {
            "account": os.environ.get("SNOWFLAKE_ACCOUNT"),
            "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE"),
            "role": os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
            "database": os.environ.get("RGA_SNOWFLAKE_DATABASE", "RGA_SYNTHETIC_TESTBED"),
        },
        "acceptance": {
            "deployment_pass": deployment.get("status") == "PASS",
            "all_benchmarks_pass": all_benchmarks_pass,
            "all_direct_semantic_result_parity_pass": all_parity_pass,
            "query_history_telemetry_complete": telemetry_complete,
            "agent_runtime_smoke_pass": agent_runtime_pass if deploy_ai else None,
            "agent_result_parity_pass": agent_answer_parity_pass if deploy_ai else None,
            "cdc_application_pass": cdc_application_pass if apply_cdc_events else None,
            "cdc_idempotency_verified": (
                bool(cdc_application and cdc_application.get("idempotency_validation"))
                if verify_cdc_idempotency
                else None
            ),
        },
        "agent_runtime": (
            {
                "status": agent_runtime.get("status"),
                "passed": agent_runtime.get("passed"),
                "failed": agent_runtime.get("failed"),
                "report": agent_runtime.get("report"),
                "result_parity_status": agent_answer_parity.get("status") if agent_answer_parity else None,
                "result_parity_report": str(agent_parity_output) if agent_parity_output else None,
            }
            if agent_runtime
            else None
        ),
        "cdc_application": (
            {
                "status": cdc_application.get("status"),
                "report": cdc_application.get("report"),
                "verify_idempotency": cdc_application.get("verify_idempotency"),
                "source_event_count": cdc_application.get("source_event_count"),
            }
            if cdc_application
            else None
        ),
        "benchmark_runs": benchmark_runs,
        "workload_analysis": str(workload_output),
        "acceleration_recommendation_count": len(workload.get("recommendations", [])),
        "external_remaining": [
            (
                "Snowflake-managed MCP client invocation evidence"
                if deploy_ai
                else "Cortex Agent/MCP live deployment, runtime smoke, and result parity"
            ),
            "Power BI XMLA governed parity",
            "Excel XMLA governed parity",
        ],
    }
    certification_path = evidence_dir / "certification_manifest.json"
    certification_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def agent_consumer_evidence(
    manifest: dict[str, Any],
    agent_report: dict[str, Any],
    *,
    evidence_dir: Path,
    security_context: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    cases = {str(case["id"]): case for case in manifest.get("cases", [])}
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for item in agent_report.get("results", []):
        case_id = str(item.get("business_query_id") or "")
        case = cases.get(case_id)
        if not case:
            continue
        output = evidence_dir / f"{case_id}.cortex_agent_mcp.json"
        if output.exists() and not overwrite:
            try:
                existing = json.loads(output.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
            if existing.get("capture_status") == "CAPTURED":
                results.append(
                    {
                        "case_id": case_id,
                        "status": "SKIPPED",
                        "error": "captured evidence already exists; use --overwrite to replace it",
                        "output": str(output),
                    }
                )
                continue

        expected = [
            str(name).upper()
            for name in (case.get("dimensions", []) + case.get("metrics", []))
        ]
        candidates = []
        for execution in item.get("analytical_executions", []) or []:
            captured = execution.get("result_rows")
            if not isinstance(captured, dict):
                continue
            columns = [str(name).upper() for name in captured.get("columns", [])]
            rows = captured.get("rows")
            if execution.get("status") not in (None, "success"):
                continue
            if captured.get("truncated"):
                continue
            if sorted(columns) != sorted(expected):
                continue
            if not isinstance(rows, list) or not rows:
                continue
            candidates.append(execution)

        if not candidates:
            results.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "error": f"no complete Agent analytical result matched expected columns {expected}",
                    "output": str(output),
                }
            )
            continue

        execution = candidates[-1]
        captured = execution["result_rows"]
        payload = {
            "case_id": case_id,
            "consumer": "cortex_agent_mcp",
            "security_context": security_context,
            "capture_status": "CAPTURED",
            "capture_method": "cortex_agent_system_execute_sql",
            "wrapper_query_id": item.get("wrapper_query_id"),
            "analytical_query_id": execution.get("query_id"),
            "analytical_sql": execution.get("sql"),
            "rows": captured["rows"],
        }
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        results.append(
            {
                "case_id": case_id,
                "status": "PASS",
                "row_count": len(captured["rows"]),
                "query_id": execution.get("query_id"),
                "output": str(output),
            }
        )

    expected_case_ids = set(cases)
    observed_case_ids = {item["case_id"] for item in results}
    for missing in sorted(expected_case_ids - observed_case_ids):
        results.append(
            {
                "case_id": missing,
                "status": "FAIL",
                "error": "Agent smoke report did not contain this verified parity case",
                "output": str(evidence_dir / f"{missing}.cortex_agent_mcp.json"),
            }
        )

    failed = sum(item["status"] == "FAIL" for item in results)
    skipped = sum(item["status"] == "SKIPPED" for item in results)
    return {
        "status": "PASS" if results and failed == 0 else "FAIL",
        "consumer": "cortex_agent_mcp",
        "security_context": security_context,
        "case_count": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


def governed_evidence_plan(
    workspace: Path,
    *,
    evidence_dir: Path,
    security_context: str,
    max_rows: int,
) -> dict[str, Any]:
    if not security_context.strip():
        raise ValueError("security_context is required")
    if max_rows < 1 or max_rows > 100000:
        raise ValueError("max_rows must be between 1 and 100000")
    manifest_path = workspace / "release" / "parity" / "parity_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"parity manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = []
    for case in manifest.get("cases", []):
        cases.append(
            {
                "case_id": case["id"],
                "question": case.get("business_question"),
                "expected_columns": case.get("dimensions", []) + case.get("metrics", []),
                "snowflake_output": str(evidence_dir / f"{case['id']}.snowflake_semantic_view.json"),
                "agent_output": str(evidence_dir / f"{case['id']}.cortex_agent_mcp.json"),
            }
        )
    return {
        "manifest": str(manifest_path),
        "evidence_dir": str(evidence_dir),
        "security_context": security_context,
        "max_rows": max_rows,
        "case_count": len(cases),
        "captured_consumers": ["snowflake_semantic_view", "cortex_agent_mcp"],
        "external_consumers_remaining": ["power_bi", "excel"],
        "cases": cases,
    }


def capture_governed_evidence(
    workspace: Path,
    *,
    evidence_dir: Path,
    security_context: str,
    max_rows: int = 10000,
    confirm: bool = False,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    plan = governed_evidence_plan(
        workspace,
        evidence_dir=evidence_dir,
        security_context=security_context,
        max_rows=max_rows,
    )
    if dry_run:
        return {"status": "DRY_RUN", **plan}
    _require_confirm(confirm, "live governed consumer evidence capture")

    configured_role = os.environ.get("SNOWFLAKE_ROLE")
    if not configured_role:
        raise RuntimeError(
            "SNOWFLAKE_ROLE must be explicitly set for governed evidence capture"
        )
    if configured_role != security_context:
        raise RuntimeError(
            f"security context mismatch: --security-context={security_context!r} "
            f"but SNOWFLAKE_ROLE={configured_role!r}"
        )

    manifest = json.loads(Path(plan["manifest"]).read_text(encoding="utf-8"))
    prepare_consumer_evidence(
        workspace,
        evidence_dir=evidence_dir,
        security_context=security_context,
        overwrite=False,
    )

    protected: list[str] = []
    for case in manifest.get("cases", []):
        for consumer in ("snowflake_semantic_view", "cortex_agent_mcp"):
            path = evidence_dir / f"{case['id']}.{consumer}.json"
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            if payload.get("capture_status") == "CAPTURED" and not overwrite:
                protected.append(str(path))
    if protected:
        raise RuntimeError(
            "captured governed evidence already exists; use --overwrite to replace: "
            + ", ".join(protected)
        )

    snowflake = _run(
        _python_script(
            "capture_snowflake_parity_evidence.py",
            "--manifest",
            plan["manifest"],
            "--evidence-dir",
            str(evidence_dir),
            "--security-context",
            security_context,
            "--max-rows",
            str(max_rows),
            "--confirm",
        ),
        capture=True,
    )
    if snowflake.returncode != 0:
        raise RuntimeError(snowflake.stdout.strip() or snowflake.stderr.strip())
    snowflake_report = json.loads(snowflake.stdout)

    agent_report = agent_smoke(
        workspace,
        confirm=True,
        dry_run=False,
        max_rows=max_rows,
    )
    if agent_report.get("status") != "PASS":
        raise RuntimeError("Cortex Agent smoke failed; governed Agent evidence was not certified")
    agent_capture = agent_consumer_evidence(
        manifest,
        agent_report,
        evidence_dir=evidence_dir,
        security_context=security_context,
        overwrite=overwrite,
    )

    status = (
        "PASS"
        if snowflake_report.get("status") == "PASS"
        and agent_capture.get("status") == "PASS"
        else "FAIL"
    )
    parity_plan = consumer_parity_plan(workspace, evidence_dir)
    return {
        "status": status,
        "security_context": security_context,
        "snowflake": snowflake_report,
        "agent": agent_capture,
        "consumer_evidence": parity_plan,
        "next": (
            "Capture the remaining Power BI and Excel PENDING evidence under the same security context, "
            "then run semantic-platform certify-consumers."
        ),
    }


def prepare_consumer_evidence(
    workspace: Path,
    *,
    evidence_dir: Path,
    security_context: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not security_context.strip():
        raise ValueError("security_context is required")
    manifest_path = workspace / "release" / "parity" / "parity_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"parity manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence_dir.mkdir(parents=True, exist_ok=True)

    instructions = {
        "snowflake_semantic_view": "Run the generated reference SQL for this case against the governed Snowflake Semantic View and capture the returned rows.",
        "cortex_agent_mcp": "Ask the governed Cortex Agent/MCP the case business question and capture the analytical result rows, not only final prose.",
        "power_bi": "Use the governed live/XMLA semantic connection and capture the visual/query rows at the exact case grain without local metric reimplementation.",
        "excel": "Use the governed live XMLA PivotTable/query path and capture the returned rows at the exact case grain without spreadsheet metric reimplementation.",
    }

    written: list[str] = []
    skipped: list[str] = []
    for case in manifest.get("cases", []):
        for consumer in manifest.get("required_consumers", []):
            path = evidence_dir / f"{case['id']}.{consumer}.json"
            if path.exists() and not overwrite:
                skipped.append(str(path))
                continue
            payload = {
                "case_id": case["id"],
                "business_question": case.get("business_question"),
                "consumer": consumer,
                "security_context": security_context,
                "capture_status": "PENDING",
                "expected_dimensions": case.get("dimensions", []),
                "expected_metrics": case.get("metrics", []),
                "capture_instructions": instructions.get(consumer, "Capture governed consumer rows for this case."),
                "rows": [],
            }
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            written.append(str(path))

    return {
        "status": "PASS",
        "evidence_dir": str(evidence_dir),
        "security_context": security_context,
        "written_count": len(written),
        "skipped_count": len(skipped),
        "written": written,
        "skipped": skipped,
        "next": (
            "Replace PENDING with CAPTURED only after real governed rows are recorded, "
            "then run semantic-platform certify-consumers."
        ),
    }


def consumer_parity_plan(
    workspace: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    manifest_path = workspace / "release" / "parity" / "parity_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"parity manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    consumers = manifest.get("required_consumers", [])
    expected: list[dict[str, Any]] = []
    for case in manifest.get("cases", []):
        for consumer in consumers:
            path = evidence_dir / f"{case['id']}.{consumer}.json"
            expected.append(
                {
                    "case_id": case["id"],
                    "consumer": consumer,
                    "path": str(path),
                    "exists": path.exists(),
                }
            )
    missing = [item for item in expected if not item["exists"]]
    captured = 0
    pending = 0
    invalid = 0
    for item in expected:
        path = Path(item["path"])
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            invalid += 1
            continue
        status = payload.get("capture_status")
        if status == "CAPTURED":
            captured += 1
        elif status == "PENDING":
            pending += 1
        else:
            invalid += 1
    return {
        "manifest": str(manifest_path),
        "evidence_dir": str(evidence_dir),
        "case_count": len(manifest.get("cases", [])),
        "consumer_count": len(consumers),
        "expected_evidence_count": len(expected),
        "present_evidence_count": len(expected) - len(missing),
        "missing_evidence_count": len(missing),
        "captured_evidence_count": captured,
        "pending_evidence_count": pending,
        "invalid_evidence_count": invalid,
        "required_consumers": consumers,
        "missing": missing,
        "evidence_contract": {
            "capture_status": "CAPTURED",
            "security_context_required": True,
            "non_empty_rows_required": True,
            "same_security_context_required": True,
        },
    }


def certify_consumers(
    workspace: Path,
    *,
    evidence_dir: Path,
    output: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = consumer_parity_plan(workspace, evidence_dir)
    if dry_run:
        return {"status": "DRY_RUN", **plan}

    output = output or (workspace / "evidence" / "cross_consumer_parity.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        _python_script(
            "validate_parity_evidence.py",
            "--manifest",
            plan["manifest"],
            "--evidence-dir",
            str(evidence_dir),
        ),
        capture=True,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip() or "consumer parity validator returned invalid output") from exc
    report["evidence_dir"] = str(evidence_dir)
    report["report"] = str(output)
    report["expected_evidence_count"] = plan["expected_evidence_count"]
    report["present_evidence_count"] = plan["present_evidence_count"]
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def ingest_consumer_evidence(
    workspace: Path,
    *,
    evidence_dir: Path,
    case_id: str,
    consumer: str,
    input_path: Path,
    security_context: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    manifest = workspace / "release" / "parity" / "parity_manifest.json"
    if not manifest.exists():
        raise FileNotFoundError(f"parity manifest not found: {manifest}")
    args = [
        "--manifest",
        str(manifest),
        "--evidence-dir",
        str(evidence_dir),
        "--case-id",
        case_id,
        "--consumer",
        consumer,
        "--input",
        str(input_path),
        "--security-context",
        security_context,
    ]
    if overwrite:
        args.append("--overwrite")
    result = _run(_python_script("ingest_consumer_evidence.py", *args), capture=True)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip() or "consumer evidence ingest returned invalid output") from exc
    if result.returncode != 0:
        raise RuntimeError(payload.get("error") or result.stdout.strip() or result.stderr.strip())
    payload["consumer_evidence"] = consumer_parity_plan(workspace, evidence_dir)
    return payload


def certification_report(
    workspace: Path,
    *,
    evidence_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    args = ["--workspace", str(workspace)]
    if evidence_dir:
        args += ["--evidence-dir", str(evidence_dir)]
    if output_dir:
        args += ["--output-dir", str(output_dir)]
    result = _run(_python_script("build_certification_report.py", *args), capture=True)
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip())
    return json.loads(result.stdout)


def release(
    output: Path,
    *,
    database: str,
    contract: Path,
    baseline: Path | None,
    source_sha: str | None,
) -> dict[str, Any]:
    args = [
        "--contract",
        str(contract),
        "--database",
        database,
        "--output",
        str(output),
    ]
    if baseline:
        args += ["--baseline", str(baseline)]
    if source_sha:
        args += ["--source-sha", source_sha]
    _run_checked(_python_script("build_semantic_release.py", *args))
    return json.loads((output / "release_manifest.json").read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semantic-platform",
        description="Governed Snowflake semantic platform operator CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("about", help="Explain the basis and architectural contract of the tool.")

    status = sub.add_parser("status", help="Show local and external readiness.")
    status.add_argument("--release-dir", type=Path)

    demo = sub.add_parser("demo-build", help="Build a complete deterministic local RGA reference workspace.")
    demo.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    demo.add_argument("--preset", choices=("tiny", "small", "medium", "large", "stress"), default="tiny")
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--policies", type=int)
    demo.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    demo.add_argument("--cdc-events-per-type", type=int, default=5)

    rel = sub.add_parser("release", help="Compile the governed semantic release bundle.")
    rel.add_argument("--output", type=Path, default=REPO_ROOT / "rga-snowflake-data-platform" / "release")
    rel.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    rel.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    rel.add_argument("--baseline", type=Path)
    rel.add_argument("--source-sha")

    scale = sub.add_parser(
        "scale-test",
        help="Run local streaming generation plus out-of-core relational validation.",
    )
    scale.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    scale.add_argument(
        "--preset",
        choices=("tiny", "small", "medium", "large", "stress"),
        default="tiny",
    )
    scale.add_argument("--policies", type=int, required=True)
    scale.add_argument("--seed", type=int, default=42)
    scale.add_argument("--memory-limit", default="512MB")
    scale.add_argument("--parquet", action="store_true")
    scale.add_argument("--row-group-size", type=int, default=100000)

    optimizer = sub.add_parser(
        "optimize",
        help="Collect Query History and build guarded Snowflake acceleration experiments.",
    )
    optimizer.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    optimizer.add_argument("--days", type=int, default=14)
    optimizer.add_argument("--limit", type=int, default=10000)
    optimizer.add_argument(
        "--query-tag-prefix",
        default="RGA_SEMANTIC_BENCHMARK",
    )
    optimizer.add_argument("--include-query-text", action="store_true")
    optimizer.add_argument("--run-diagnostics", action="store_true")
    optimizer.add_argument("--confirm", action="store_true")
    optimizer.add_argument("--dry-run", action="store_true")

    evaluator = sub.add_parser(
        "evaluate-optimization",
        help="Compare before/after benchmark evidence and gate a physical optimization.",
    )
    evaluator.add_argument("--before", type=Path, action="append", required=True)
    evaluator.add_argument("--after", type=Path, action="append", required=True)
    evaluator.add_argument(
        "--target-variant",
        choices=("direct", "semantic", "both"),
        default="both",
    )
    evaluator.add_argument("--min-p95-improvement-pct", type=float, default=10.0)
    evaluator.add_argument("--max-scan-regression-pct", type=float, default=25.0)
    evaluator.add_argument("--output", type=Path)

    live = sub.add_parser("snowflake-demo", help="Run the generated demo through Snowflake and dbt.")
    live.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    live.add_argument("--confirm", action="store_true")
    live.add_argument("--deploy-semantic", action="store_true")
    live.add_argument("--deploy-ai", action="store_true")

    cdc = sub.add_parser(
        "apply-cdc",
        help="Plan or execute the idempotent CDC correction/late-arrival cycle.",
    )
    cdc.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    cdc.add_argument("--confirm", action="store_true")
    cdc.add_argument("--dry-run", action="store_true")
    cdc.add_argument("--verify-idempotency", action="store_true")

    bench = sub.add_parser("benchmark", help="Run or dry-run direct-vs-semantic Snowflake benchmarks.")
    bench.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    bench.add_argument("--mode", choices=("direct", "semantic", "both"), default="both")
    bench.add_argument("--concurrency", type=int, default=5)
    bench.add_argument("--iterations", type=int, default=3)
    bench.add_argument("--dry-run", action="store_true")
    bench.add_argument("--confirm-live", action="store_true")

    agent = sub.add_parser(
        "agent-smoke",
        help="Dry-run or execute governed Cortex Agent runtime smoke questions.",
    )
    agent.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    agent.add_argument("--agent")
    agent.add_argument("--question", action="append")
    agent.add_argument("--confirm", action="store_true")
    agent.add_argument("--dry-run", action="store_true")

    certify = sub.add_parser(
        "certify-live",
        help="Run or plan end-to-end Snowflake semantic runtime certification.",
    )
    certify.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    certify.add_argument("--concurrency", default="1,5,10,25,50")
    certify.add_argument("--iterations", type=int, default=3)
    certify.add_argument("--deploy-ai", action="store_true")
    certify.add_argument("--apply-cdc", action="store_true")
    certify.add_argument("--verify-cdc-idempotency", action="store_true")
    certify.add_argument("--confirm", action="store_true")
    certify.add_argument("--dry-run", action="store_true")

    capture_governed = sub.add_parser(
        "capture-governed-evidence",
        help="Capture live Snowflake Semantic View and Cortex Agent parity rows.",
    )
    capture_governed.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    capture_governed.add_argument("--evidence-dir", type=Path, required=True)
    capture_governed.add_argument("--security-context", required=True)
    capture_governed.add_argument("--max-rows", type=int, default=10000)
    capture_governed.add_argument("--overwrite", action="store_true")
    capture_governed.add_argument("--confirm", action="store_true")
    capture_governed.add_argument("--dry-run", action="store_true")

    prepare_consumers = sub.add_parser(
        "prepare-consumer-evidence",
        help="Create non-certifiable Snowflake/AI/Power BI/Excel evidence templates.",
    )
    prepare_consumers.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    prepare_consumers.add_argument("--evidence-dir", type=Path, required=True)
    prepare_consumers.add_argument("--security-context", required=True)
    prepare_consumers.add_argument("--overwrite", action="store_true")

    ingest = sub.add_parser(
        "ingest-consumer-evidence",
        help="Import captured Power BI or Excel CSV/JSON rows into parity evidence.",
    )
    ingest.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    ingest.add_argument("--evidence-dir", type=Path, required=True)
    ingest.add_argument("--case-id", required=True)
    ingest.add_argument("--consumer", choices=("power_bi", "excel"), required=True)
    ingest.add_argument("--input", type=Path, required=True)
    ingest.add_argument("--security-context", required=True)
    ingest.add_argument("--overwrite", action="store_true")

    report = sub.add_parser(
        "certification-report",
        help="Build one truthful certification summary across repository, live runtime, and consumer evidence.",
    )
    report.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    report.add_argument("--evidence-dir", type=Path)
    report.add_argument("--output-dir", type=Path)

    consumers = sub.add_parser(
        "certify-consumers",
        help="Plan or validate Snowflake/AI/Power BI/Excel parity evidence.",
    )
    consumers.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    consumers.add_argument("--evidence-dir", type=Path, required=True)
    consumers.add_argument("--output", type=Path)
    consumers.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "about":
            print(_json(PRODUCT_BASIS))
            return 0
        if args.command == "status":
            print(_json(readiness_status(release_dir=args.release_dir)))
            return 0
        if args.command == "demo-build":
            print(
                _json(
                    build_demo(
                        args.workspace,
                        preset=args.preset,
                        seed=args.seed,
                        policies=args.policies,
                        database=args.database,
                        cdc_events_per_type=args.cdc_events_per_type,
                    )
                )
            )
            return 0
        if args.command == "release":
            print(_json(release(args.output, database=args.database, contract=args.contract, baseline=args.baseline, source_sha=args.source_sha)))
            return 0
        if args.command == "scale-test":
            result = scale_test(
                args.workspace,
                preset=args.preset,
                policies=args.policies,
                seed=args.seed,
                memory_limit=args.memory_limit,
                parquet=args.parquet,
                row_group_size=args.row_group_size,
            )
            print(_json(result))
            return 0
        if args.command == "optimize":
            result = optimize(
                args.workspace,
                days=args.days,
                limit=args.limit,
                query_tag_prefix=args.query_tag_prefix,
                confirm=args.confirm,
                dry_run=args.dry_run,
                include_query_text=args.include_query_text,
                run_diagnostics=args.run_diagnostics,
            )
            print(_json(result))
            return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1
        if args.command == "evaluate-optimization":
            result = evaluate_optimization(
                before_reports=args.before,
                after_reports=args.after,
                target_variant=args.target_variant,
                min_p95_improvement_pct=args.min_p95_improvement_pct,
                max_scan_regression_pct=args.max_scan_regression_pct,
                output=args.output,
            )
            print(_json(result))
            return 0 if result.get("decision") == "ACCEPT" else 3
        if args.command == "snowflake-demo":
            print(
                _json(
                    snowflake_demo(
                        args.workspace,
                        confirm=args.confirm,
                        deploy_semantic=args.deploy_semantic,
                        deploy_ai=args.deploy_ai,
                    )
                )
            )
            return 0
        if args.command == "apply-cdc":
            result = apply_cdc(
                args.workspace,
                confirm=args.confirm,
                dry_run=args.dry_run,
                verify_idempotency=args.verify_idempotency,
            )
            print(_json(result))
            return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1
        if args.command == "benchmark":
            print(
                _json(
                    benchmark(
                        args.workspace,
                        dry_run=args.dry_run,
                        confirm_live=args.confirm_live,
                        concurrency=args.concurrency,
                        iterations=args.iterations,
                        mode=args.mode,
                    )
                )
            )
            return 0
        if args.command == "agent-smoke":
            result = agent_smoke(
                args.workspace,
                confirm=args.confirm,
                dry_run=args.dry_run,
                agent=args.agent,
                questions=args.question,
            )
            print(_json(result))
            return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1
        if args.command == "capture-governed-evidence":
            result = capture_governed_evidence(
                args.workspace,
                evidence_dir=args.evidence_dir,
                security_context=args.security_context,
                max_rows=args.max_rows,
                confirm=args.confirm,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
            )
            print(_json(result))
            return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1
        if args.command == "prepare-consumer-evidence":
            result = prepare_consumer_evidence(
                args.workspace,
                evidence_dir=args.evidence_dir,
                security_context=args.security_context,
                overwrite=args.overwrite,
            )
            print(_json(result))
            return 0
        if args.command == "ingest-consumer-evidence":
            result = ingest_consumer_evidence(
                args.workspace,
                evidence_dir=args.evidence_dir,
                case_id=args.case_id,
                consumer=args.consumer,
                input_path=args.input,
                security_context=args.security_context,
                overwrite=args.overwrite,
            )
            print(_json(result))
            return 0
        if args.command == "certification-report":
            result = certification_report(
                args.workspace,
                evidence_dir=args.evidence_dir,
                output_dir=args.output_dir,
            )
            print(_json(result))
            return 0
        if args.command == "certify-consumers":
            result = certify_consumers(
                args.workspace,
                evidence_dir=args.evidence_dir,
                output=args.output,
                dry_run=args.dry_run,
            )
            print(_json(result))
            return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1
        if args.command == "certify-live":
            result = certify_live(
                args.workspace,
                confirm=args.confirm,
                dry_run=args.dry_run,
                concurrency=parse_concurrency_sweep(args.concurrency),
                iterations=args.iterations,
                deploy_ai=args.deploy_ai,
                apply_cdc_events=args.apply_cdc,
                verify_cdc_idempotency=args.verify_cdc_idempotency,
            )
            print(_json(result))
            return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(_json({"status": "FAIL", "error": str(exc)}))
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
