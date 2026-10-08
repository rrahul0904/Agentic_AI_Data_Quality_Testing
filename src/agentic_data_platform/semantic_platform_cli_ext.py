"""Extension commands for external governed-consumer evidence.

All existing semantic-platform commands delegate unchanged to semantic_platform_cli.
This thin layer adds Excel XMLA evidence capture, Snowflake-managed MCP remote
invocation evidence, and one end-to-end all-consumer capture/certification command.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from . import semantic_platform_cli as base


def capture_excel_evidence(
    workspace: Path,
    *,
    evidence_dir: Path,
    security_context: str,
    runner: str | None = None,
    cube_name: str | None = None,
    connection_string_env: str = "EXCEL_XMLA_CONNECTION_STRING",
    max_rows: int = 100000,
    query_timeout: int = 300,
    confirm: bool = False,
    dry_run: bool = False,
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
        "--security-context",
        security_context,
        "--connection-string-env",
        connection_string_env,
        "--max-rows",
        str(max_rows),
        "--query-timeout",
        str(query_timeout),
    ]
    if runner:
        args += ["--runner", runner]
    if cube_name:
        args += ["--cube-name", cube_name]
    if overwrite:
        args.append("--overwrite")
    if dry_run:
        args.append("--dry-run")
    elif confirm:
        args.append("--confirm")

    result = base._run(
        base._python_script("capture_excel_parity_evidence.py", *args),
        capture=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            result.stdout.strip()
            or result.stderr.strip()
            or "Excel XMLA parity capture returned invalid output"
        ) from exc
    if result.returncode != 0:
        if dry_run and payload.get("status") == "DRY_RUN":
            return payload
        raise RuntimeError(
            payload.get("error")
            or "; ".join(payload.get("errors", []))
            or result.stdout.strip()
            or result.stderr.strip()
        )
    payload["consumer_evidence"] = base.consumer_parity_plan(
        workspace,
        evidence_dir,
    )
    return payload


def _workspace_mcp_defaults(workspace: Path) -> dict[str, str]:
    mcp_spec_path = workspace / "release" / "ai" / "mcp_spec.yml"
    parity_path = workspace / "release" / "parity" / "parity_manifest.json"
    if not mcp_spec_path.exists():
        raise FileNotFoundError(f"MCP specification not found: {mcp_spec_path}")
    if not parity_path.exists():
        raise FileNotFoundError(f"parity manifest not found: {parity_path}")

    spec = yaml.safe_load(mcp_spec_path.read_text(encoding="utf-8")) or {}
    tools = spec.get("tools") or []
    if not tools or not isinstance(tools[0], dict) or not tools[0].get("name"):
        raise ValueError("MCP specification does not expose a named governed tool")

    parity = json.loads(parity_path.read_text(encoding="utf-8"))
    cases = parity.get("cases") or []
    if not cases or not cases[0].get("business_question"):
        raise ValueError("parity manifest has no verified business question for MCP smoke")
    return {
        "expected_tool": str(tools[0]["name"]),
        "question": str(cases[0]["business_question"]),
        "mcp_spec": str(mcp_spec_path),
        "parity_manifest": str(parity_path),
    }


def mcp_remote_smoke(
    workspace: Path,
    *,
    endpoint: str | None = None,
    account_url: str | None = None,
    database: str | None = None,
    schema: str = "AI",
    server: str | None = None,
    expected_tool: str | None = None,
    question: str | None = None,
    token_env: str = "SNOWFLAKE_MCP_ACCESS_TOKEN",
    timeout: int = 120,
    output: Path | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    defaults = _workspace_mcp_defaults(workspace)
    expected_tool = expected_tool or defaults["expected_tool"]
    question = question or defaults["question"]
    output = output or (workspace / "evidence" / "mcp_remote_smoke.json")

    args = [
        "--expected-tool",
        expected_tool,
        "--question",
        question,
        "--token-env",
        token_env,
        "--timeout",
        str(timeout),
    ]
    if endpoint:
        args += ["--endpoint", endpoint]
    else:
        if account_url:
            args += ["--account-url", account_url]
        if database:
            args += ["--database", database]
        if schema:
            args += ["--schema", schema]
        if server:
            args += ["--server", server]
    if dry_run:
        args.append("--dry-run")
    else:
        args += ["--output", str(output)]
        if confirm:
            args.append("--confirm")

    result = base._run(
        base._python_script("smoke_snowflake_mcp.py", *args),
        capture=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            result.stdout.strip()
            or result.stderr.strip()
            or "Snowflake MCP smoke returned invalid output"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            payload.get("error")
            or "; ".join(payload.get("errors", []))
            or result.stdout.strip()
            or result.stderr.strip()
        )
    payload["source_mcp_spec"] = defaults["mcp_spec"]
    payload["source_parity_manifest"] = defaults["parity_manifest"]
    if not dry_run:
        payload["evidence"] = str(output)
    return payload


def capture_all_evidence(
    workspace: Path,
    *,
    evidence_dir: Path,
    security_context: str,
    max_rows: int = 10000,
    power_bi_workspace_id: str | None = None,
    power_bi_dataset_id: str | None = None,
    power_bi_effective_username: str | None = None,
    power_bi_roles: list[str] | None = None,
    power_bi_query_timeout: int = 300,
    excel_runner: str | None = None,
    excel_cube_name: str | None = None,
    excel_connection_string_env: str = "EXCEL_XMLA_CONNECTION_STRING",
    excel_query_timeout: int = 300,
    confirm: bool = False,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    governed = base.capture_governed_evidence(
        workspace,
        evidence_dir=evidence_dir,
        security_context=security_context,
        max_rows=max_rows,
        confirm=confirm,
        dry_run=dry_run,
        overwrite=overwrite,
        capture_power_bi=True,
        power_bi_workspace_id=power_bi_workspace_id,
        power_bi_dataset_id=power_bi_dataset_id,
        power_bi_effective_username=power_bi_effective_username,
        power_bi_roles=power_bi_roles,
        power_bi_query_timeout=power_bi_query_timeout,
    )
    excel = capture_excel_evidence(
        workspace,
        evidence_dir=evidence_dir,
        security_context=security_context,
        runner=excel_runner,
        cube_name=excel_cube_name,
        connection_string_env=excel_connection_string_env,
        max_rows=max_rows,
        query_timeout=excel_query_timeout,
        confirm=confirm,
        dry_run=dry_run,
        overwrite=overwrite,
    )

    if dry_run:
        return {
            "status": "DRY_RUN",
            "security_context": security_context,
            "governed": governed,
            "excel": excel,
            "planned_consumers": [
                "snowflake_semantic_view",
                "cortex_agent_mcp",
                "power_bi",
                "excel",
            ],
            "next": "Provide target Snowflake, Power BI, and Excel/XMLA configuration and rerun with --confirm.",
        }

    plan = base.consumer_parity_plan(workspace, evidence_dir)
    all_captured = (
        plan["captured_evidence_count"] == plan["expected_evidence_count"]
        and plan["missing_evidence_count"] == 0
        and plan["pending_evidence_count"] == 0
        and plan["invalid_evidence_count"] == 0
    )
    parity = (
        base.certify_consumers(
            workspace,
            evidence_dir=evidence_dir,
            dry_run=False,
        )
        if all_captured
        else None
    )
    status = (
        "PASS"
        if governed.get("status") == "PASS"
        and excel.get("status") == "PASS"
        and all_captured
        and isinstance(parity, dict)
        and parity.get("status") == "PASS"
        else "FAIL"
    )
    return {
        "status": status,
        "security_context": security_context,
        "governed": governed,
        "excel": excel,
        "consumer_evidence": plan,
        "cross_consumer_parity": parity,
        "external_consumers_remaining": [] if all_captured else ["incomplete_consumer_evidence"],
        "truth_boundary": (
            "PASS requires captured Snowflake Semantic View, Cortex Agent/MCP, Power BI, and Excel XMLA rows "
            "under the same security-context label plus passing cross-consumer value parity. Excel automation "
            "certifies the XMLA/MDX path rather than opening the interactive Excel desktop UI."
        ),
    }


def _extension_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semantic-platform")
    sub = parser.add_subparsers(dest="command", required=True)

    excel = sub.add_parser(
        "capture-excel-evidence",
        help="Capture governed Excel parity rows through the XMLA/MDX runner.",
    )
    excel.add_argument("--workspace", type=Path, default=base.DEFAULT_WORKSPACE)
    excel.add_argument("--evidence-dir", type=Path, required=True)
    excel.add_argument("--security-context", required=True)
    excel.add_argument("--runner")
    excel.add_argument("--cube-name")
    excel.add_argument("--connection-string-env", default="EXCEL_XMLA_CONNECTION_STRING")
    excel.add_argument("--max-rows", type=int, default=100000)
    excel.add_argument("--query-timeout", type=int, default=300)
    excel.add_argument("--overwrite", action="store_true")
    excel.add_argument("--confirm", action="store_true")
    excel.add_argument("--dry-run", action="store_true")

    mcp = sub.add_parser(
        "mcp-smoke",
        help="Discover and invoke the governed Snowflake-managed MCP Agent tool.",
    )
    mcp.add_argument("--workspace", type=Path, default=base.DEFAULT_WORKSPACE)
    mcp.add_argument("--endpoint")
    mcp.add_argument("--account-url")
    mcp.add_argument("--database")
    mcp.add_argument("--schema", default="AI")
    mcp.add_argument("--server")
    mcp.add_argument("--expected-tool")
    mcp.add_argument("--question")
    mcp.add_argument("--token-env", default="SNOWFLAKE_MCP_ACCESS_TOKEN")
    mcp.add_argument("--timeout", type=int, default=120)
    mcp.add_argument("--output", type=Path)
    mcp.add_argument("--confirm", action="store_true")
    mcp.add_argument("--dry-run", action="store_true")

    all_evidence = sub.add_parser(
        "capture-all-evidence",
        help="Capture Snowflake, Agent, Power BI, and Excel evidence and run the parity gate.",
    )
    all_evidence.add_argument("--workspace", type=Path, default=base.DEFAULT_WORKSPACE)
    all_evidence.add_argument("--evidence-dir", type=Path, required=True)
    all_evidence.add_argument("--security-context", required=True)
    all_evidence.add_argument("--max-rows", type=int, default=10000)
    all_evidence.add_argument("--power-bi-workspace-id")
    all_evidence.add_argument("--power-bi-dataset-id")
    all_evidence.add_argument("--power-bi-effective-username")
    all_evidence.add_argument("--power-bi-role", action="append", default=[])
    all_evidence.add_argument("--power-bi-query-timeout", type=int, default=300)
    all_evidence.add_argument("--excel-runner")
    all_evidence.add_argument("--excel-cube-name")
    all_evidence.add_argument("--excel-connection-string-env", default="EXCEL_XMLA_CONNECTION_STRING")
    all_evidence.add_argument("--excel-query-timeout", type=int, default=300)
    all_evidence.add_argument("--overwrite", action="store_true")
    all_evidence.add_argument("--confirm", action="store_true")
    all_evidence.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else None
    extension_commands = {
        "capture-excel-evidence",
        "capture-all-evidence",
        "mcp-smoke",
    }
    if command not in extension_commands:
        return base.main()

    args = _extension_parser().parse_args()
    try:
        if args.command == "capture-excel-evidence":
            result = capture_excel_evidence(
                args.workspace,
                evidence_dir=args.evidence_dir,
                security_context=args.security_context,
                runner=args.runner,
                cube_name=args.cube_name,
                connection_string_env=args.connection_string_env,
                max_rows=args.max_rows,
                query_timeout=args.query_timeout,
                confirm=args.confirm,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
            )
        elif args.command == "mcp-smoke":
            result = mcp_remote_smoke(
                args.workspace,
                endpoint=args.endpoint,
                account_url=args.account_url,
                database=args.database,
                schema=args.schema,
                server=args.server,
                expected_tool=args.expected_tool,
                question=args.question,
                token_env=args.token_env,
                timeout=args.timeout,
                output=args.output,
                confirm=args.confirm,
                dry_run=args.dry_run,
            )
        else:
            result = capture_all_evidence(
                args.workspace,
                evidence_dir=args.evidence_dir,
                security_context=args.security_context,
                max_rows=args.max_rows,
                power_bi_workspace_id=args.power_bi_workspace_id,
                power_bi_dataset_id=args.power_bi_dataset_id,
                power_bi_effective_username=args.power_bi_effective_username,
                power_bi_roles=args.power_bi_role,
                power_bi_query_timeout=args.power_bi_query_timeout,
                excel_runner=args.excel_runner,
                excel_cube_name=args.excel_cube_name,
                excel_connection_string_env=args.excel_connection_string_env,
                excel_query_timeout=args.excel_query_timeout,
                confirm=args.confirm,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
            )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(base._json({"status": "ERROR", "error": str(exc)}))
        return 2

    print(base._json(result))
    return 0 if result.get("status") in {"PASS", "DRY_RUN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
