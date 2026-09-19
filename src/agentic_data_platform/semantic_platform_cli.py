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
) -> dict[str, Any]:
    data_dir = workspace / "data"
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
        "paths": {
            "data": str(data_dir),
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
) -> dict[str, Any]:
    plan = demo_plan(workspace, preset=preset, seed=seed, policies=policies, database=database)
    workspace.mkdir(parents=True, exist_ok=True)
    steps = []
    for command in plan["commands"]:
        steps.append(_run_checked(command))
    release_manifest = Path(plan["paths"]["release"]) / "release_manifest.json"
    data_manifest = Path(plan["paths"]["data"]) / "manifest.json"
    return {
        "status": "PASS",
        "basis": PRODUCT_BASIS,
        "workspace": str(workspace),
        "data_manifest": json.loads(data_manifest.read_text(encoding="utf-8")),
        "release_manifest": json.loads(release_manifest.read_text(encoding="utf-8")),
        "steps": [{"command": item["command"], "returncode": item["returncode"]} for item in steps],
        "next": {
            "snowflake_demo": "semantic-platform snowflake-demo --workspace <workspace> --confirm",
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
) -> dict[str, Any]:
    if iterations < 1 or iterations > 100:
        raise ValueError("iterations must be between 1 and 100")
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
        },
        "benchmark": {
            "mode": "both",
            "concurrency": concurrency,
            "iterations": iterations,
            "requires_result_parity": True,
            "requires_query_history_telemetry": True,
        },
        "evidence": {
            "directory": str(workspace / "evidence"),
            "workload_analysis": str(workspace / "evidence" / "workload_analysis.json"),
            "agent_smoke": str(workspace / "evidence" / "agent_smoke.json") if deploy_ai else None,
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
) -> dict[str, Any]:
    release_manifest_path = workspace / "release" / "release_manifest.json"
    database = "RGA_SYNTHETIC_TESTBED"
    if release_manifest_path.exists():
        release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
        database = release_manifest.get("database") or database
    agent_name = agent or f"{database}.AI.RGA_REINSURANCE_AGENT"
    output = workspace / "evidence" / "agent_smoke.json"
    args = ["--agent", agent_name, "--output", str(output)]
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


def certify_live(
    workspace: Path,
    *,
    confirm: bool,
    dry_run: bool,
    concurrency: list[int],
    iterations: int,
    deploy_ai: bool,
) -> dict[str, Any]:
    plan = certification_plan(
        workspace,
        concurrency=concurrency,
        iterations=iterations,
        deploy_ai=deploy_ai,
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
    certification_pass = (
        all_benchmarks_pass
        and all_parity_pass
        and telemetry_complete
        and agent_runtime_pass
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
        },
        "agent_runtime": (
            {
                "status": agent_runtime.get("status"),
                "passed": agent_runtime.get("passed"),
                "failed": agent_runtime.get("failed"),
                "report": agent_runtime.get("report"),
            }
            if agent_runtime
            else None
        ),
        "benchmark_runs": benchmark_runs,
        "workload_analysis": str(workload_output),
        "acceleration_recommendation_count": len(workload.get("recommendations", [])),
        "external_remaining": [
            (
                "Cortex Agent numerical/answer parity against canonical query results"
                if deploy_ai
                else "Cortex Agent/MCP live deployment and governed runtime smoke"
            ),
            "Power BI XMLA governed parity",
            "Excel XMLA governed parity",
        ],
    }
    certification_path = evidence_dir / "certification_manifest.json"
    certification_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


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

    rel = sub.add_parser("release", help="Compile the governed semantic release bundle.")
    rel.add_argument("--output", type=Path, default=REPO_ROOT / "rga-snowflake-data-platform" / "release")
    rel.add_argument("--database", default="RGA_SYNTHETIC_TESTBED")
    rel.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    rel.add_argument("--baseline", type=Path)
    rel.add_argument("--source-sha")

    live = sub.add_parser("snowflake-demo", help="Run the generated demo through Snowflake and dbt.")
    live.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    live.add_argument("--confirm", action="store_true")
    live.add_argument("--deploy-semantic", action="store_true")
    live.add_argument("--deploy-ai", action="store_true")

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
    certify.add_argument("--confirm", action="store_true")
    certify.add_argument("--dry-run", action="store_true")

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
                    )
                )
            )
            return 0
        if args.command == "release":
            print(_json(release(args.output, database=args.database, contract=args.contract, baseline=args.baseline, source_sha=args.source_sha)))
            return 0
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
        if args.command == "certify-live":
            result = certify_live(
                args.workspace,
                confirm=args.confirm,
                dry_run=args.dry_run,
                concurrency=parse_concurrency_sweep(args.concurrency),
                iterations=args.iterations,
                deploy_ai=args.deploy_ai,
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
