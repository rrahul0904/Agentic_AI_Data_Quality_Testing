#!/usr/bin/env python3
"""Capture governed Excel parity evidence through an XMLA/ADOMD MDX runner."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

DEFAULT_CONNECTION_ENV = "EXCEL_XMLA_CONNECTION_STRING"
DEFAULT_CUBE_ENV = "EXCEL_XMLA_CUBE"
DEFAULT_RUNNER_ENV = "EXCEL_XMLA_RUNNER"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--security-context", required=True)
    parser.add_argument("--runner")
    parser.add_argument("--cube-name")
    parser.add_argument(
        "--connection-string-env",
        default=DEFAULT_CONNECTION_ENV,
        help="Environment variable containing the XMLA connection string. The value is never persisted.",
    )
    parser.add_argument("--max-rows", type=int, default=100000)
    parser.add_argument("--query-timeout", type=int, default=300)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def default_runner_command() -> str | None:
    configured = os.environ.get(DEFAULT_RUNNER_ENV)
    if configured:
        return configured
    script = Path(__file__).with_name("excel_xmla_runner.ps1")
    pwsh = shutil.which("pwsh")
    if pwsh and script.exists():
        return f'{shlex.quote(pwsh)} -NoProfile -File {shlex.quote(str(script))}'
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell and script.exists():
        return f'{shlex.quote(powershell)} -NoProfile -File {shlex.quote(str(script))}'
    return None


def resolve_config(
    env: dict[str, str],
    *,
    runner: str | None,
    cube_name: str | None,
    connection_string_env: str,
) -> dict[str, Any]:
    runner_command = runner or env.get(DEFAULT_RUNNER_ENV) or default_runner_command()
    cube = cube_name or env.get(DEFAULT_CUBE_ENV)
    return {
        "runner_command": runner_command,
        "cube_name": cube,
        "connection_string_env": connection_string_env,
        "connection_configured": bool(env.get(connection_string_env)),
    }


def validate_request(
    manifest: Path,
    *,
    config: dict[str, Any],
    security_context: str,
    max_rows: int,
    query_timeout: int,
    confirm: bool,
    dry_run: bool,
) -> list[str]:
    errors: list[str] = []
    if not manifest.exists():
        errors.append(f"parity manifest not found: {manifest}")
    if not security_context.strip():
        errors.append("security_context is required")
    if max_rows < 1 or max_rows > 1_000_000:
        errors.append("max_rows must be between 1 and 1000000")
    if query_timeout < 1 or query_timeout > 3600:
        errors.append("query_timeout must be between 1 and 3600 seconds")
    if not dry_run:
        if not config.get("runner_command"):
            errors.append(
                "Excel XMLA runner is required via --runner/EXCEL_XMLA_RUNNER "
                "or an installed PowerShell executable with excel_xmla_runner.ps1"
            )
        if not config.get("cube_name"):
            errors.append(
                "Excel XMLA cube/model name is required via --cube-name or EXCEL_XMLA_CUBE"
            )
        if not config.get("connection_configured"):
            errors.append(
                "Excel XMLA connection is required via environment variable "
                f"{config.get('connection_string_env')}"
            )
        if not confirm:
            errors.append("Refusing live Excel evidence capture without --confirm")
    return errors


def render_cube_name(mdx: str, cube_name: str, token: str = "__CUBE_NAME__") -> str:
    if token not in mdx:
        raise ValueError(f"MDX query is missing cube token {token}")
    escaped = str(cube_name).replace("]", "]]" )
    return mdx.replace(token, escaped)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def normalize_xmla_column(name: str) -> str:
    value = str(name).strip()
    tokens = re.findall(r"\[([^\]]+)\]", value)
    ignored = {
        "MEMBER_CAPTION",
        "MEMBER_UNIQUE_NAME",
        "MEMBER_VALUE",
        "LEVEL_NUMBER",
    }
    for token in reversed(tokens):
        upper = token.upper()
        if upper not in ignored and upper not in {"MEASURES"}:
            return upper
    return value.strip("[]").upper()


def normalize_rows(
    response: dict[str, Any],
    expected_columns: list[str],
    *,
    max_rows: int,
) -> list[dict[str, Any]]:
    rows = response.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Excel XMLA query returned no rows")
    if len(rows) > max_rows:
        raise ValueError(
            f"Excel XMLA runner returned {len(rows)} rows, above max_rows={max_rows}"
        )
    expected = [str(name).upper() for name in expected_columns]
    columns = response.get("columns")
    if columns is not None and not isinstance(columns, list):
        raise ValueError("Excel XMLA runner columns must be a list when provided")

    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if isinstance(row, list):
            if len(row) != len(expected):
                raise ValueError(
                    f"row {index} column-count mismatch: expected {len(expected)}, got {len(row)}"
                )
            normalized.append(
                {name: _jsonable(row[position]) for position, name in enumerate(expected)}
            )
            continue

        if not isinstance(row, dict):
            raise ValueError(f"row {index} must be an array or object")

        keyed: dict[str, Any] = {}
        for key, value in row.items():
            normalized_key = normalize_xmla_column(str(key))
            if normalized_key in keyed:
                raise ValueError(
                    f"row {index} has duplicate normalized column {normalized_key}"
                )
            keyed[normalized_key] = _jsonable(value)
        if sorted(keyed) == sorted(expected):
            normalized.append({name: keyed[name] for name in expected})
            continue

        if columns and len(columns) == len(expected) and all(str(name) in row for name in columns):
            normalized.append(
                {
                    expected[position]: _jsonable(row[str(column)])
                    for position, column in enumerate(columns)
                }
            )
            continue

        raise ValueError(
            f"row {index} column mismatch: expected {expected}, got {sorted(keyed)}"
        )
    return normalized


def _redact(text: str, secrets: list[str]) -> str:
    value = text
    for secret in secrets:
        if secret:
            value = value.replace(secret, "<redacted>")
    return value


def safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("password", "secret", "token", "credential", "connection")):
                continue
            result[str(key)] = safe_metadata(item)
        return result
    if isinstance(value, list):
        return [safe_metadata(item) for item in value]
    return _jsonable(value)


def execute_runner(
    runner_command: str,
    request: dict[str, Any],
    *,
    query_timeout: int,
) -> dict[str, Any]:
    command = shlex.split(runner_command)
    if not command:
        raise ValueError("Excel XMLA runner command is empty")
    connection_string = str(request.get("connection_string") or "")
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=max(30, query_timeout + 30),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Excel XMLA runner exceeded timeout ({query_timeout}s)"
        ) from exc
    if completed.returncode != 0:
        detail = _redact(
            (completed.stderr or completed.stdout or "runner failed").strip(),
            [connection_string],
        )
        raise RuntimeError(
            f"Excel XMLA runner failed with exit code {completed.returncode}: {detail}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        detail = _redact(completed.stdout.strip(), [connection_string])
        raise RuntimeError(
            f"Excel XMLA runner returned invalid JSON: {detail[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Excel XMLA runner must return a JSON object")
    if payload.get("status") not in (None, "PASS"):
        raise RuntimeError(
            "Excel XMLA runner reported failure: "
            + str(payload.get("error") or payload.get("status"))
        )
    return payload


def plan(
    manifest_path: Path,
    *,
    evidence_dir: Path,
    config: dict[str, Any],
    security_context: str,
    max_rows: int,
    query_timeout: int,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    cases: list[dict[str, Any]] = []
    for case in manifest.get("cases", []):
        excel = case.get("excel", {})
        mdx_file = excel.get("mdx_file")
        path = manifest_path.parent / str(mdx_file) if mdx_file else None
        cases.append(
            {
                "case_id": case.get("id"),
                "mdx_file": str(path) if path else None,
                "mdx_exists": bool(path and path.exists()),
                "output": str(evidence_dir / f"{case.get('id')}.excel.json"),
                "expected_columns": case.get("dimensions", []) + case.get("metrics", []),
            }
        )
    return {
        "status": "DRY_RUN",
        "manifest": str(manifest_path),
        "evidence_dir": str(evidence_dir),
        "security_context": security_context,
        "runner_configured": bool(config.get("runner_command")),
        "cube_name": config.get("cube_name"),
        "connection_string_env": config.get("connection_string_env"),
        "connection_configured": bool(config.get("connection_configured")),
        "max_rows": max_rows,
        "query_timeout": query_timeout,
        "case_count": len(cases),
        "cases": cases,
        "protocol": "XMLA/ADOMD MDX",
        "truth_boundary": (
            "This path certifies Excel-compatible XMLA/MDX results when executed against the "
            "same governed semantic endpoint/model used by Excel. It does not claim that an "
            "interactive Excel workbook UI was opened by the automation."
        ),
    }


def capture(
    manifest_path: Path,
    evidence_dir: Path,
    *,
    env: dict[str, str],
    runner_command: str,
    cube_name: str,
    connection_string_env: str,
    security_context: str,
    max_rows: int,
    query_timeout: int,
    overwrite: bool,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    connection_string = env.get(connection_string_env)
    if not connection_string:
        raise ValueError(f"Excel XMLA connection is not configured in {connection_string_env}")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for case in manifest.get("cases", []):
        case_id = str(case["id"])
        output = evidence_dir / f"{case_id}.excel.json"
        if output.exists() and not overwrite:
            existing = load_json(output)
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

        excel = case.get("excel", {})
        mdx_file = excel.get("mdx_file")
        if not mdx_file:
            results.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "error": "parity case does not define excel.mdx_file",
                    "output": str(output),
                }
            )
            continue
        mdx_path = manifest_path.parent / str(mdx_file)
        if not mdx_path.exists():
            results.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "error": f"MDX file not found: {mdx_path}",
                    "output": str(output),
                }
            )
            continue

        template = mdx_path.read_text(encoding="utf-8")
        token = str(excel.get("cube_name_token") or "__CUBE_NAME__")
        try:
            mdx = render_cube_name(template, cube_name, token)
            response = execute_runner(
                runner_command,
                {
                    "connection_string": connection_string,
                    "query": mdx,
                    "max_rows": max_rows,
                    "timeout_seconds": query_timeout,
                },
                query_timeout=query_timeout,
            )
            rows = normalize_rows(
                response,
                case.get("dimensions", []) + case.get("metrics", []),
                max_rows=max_rows,
            )
            if (
                not rows
                and not case.get("acceptance", {}).get("allow_empty_result", False)
            ):
                raise ValueError("Excel evidence rows must not be empty")
        except Exception as exc:
            results.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "error": _redact(str(exc), [connection_string]),
                    "output": str(output),
                }
            )
            continue

        runner_tokens = shlex.split(runner_command)
        payload = {
            "case_id": case_id,
            "business_question": case.get("business_question"),
            "consumer": "excel",
            "security_context": security_context,
            "capture_status": "CAPTURED",
            "capture_method": "xmla_adomd_mdx_runner",
            "cube_name": cube_name,
            "runner": Path(runner_tokens[0]).name if runner_tokens else "unknown",
            "connection_string_env": connection_string_env,
            "mdx_file": str(mdx_path),
            "mdx_template_sha256": hashlib.sha256(template.encode("utf-8")).hexdigest(),
            "mdx_rendered_sha256": hashlib.sha256(mdx.encode("utf-8")).hexdigest(),
            "runner_metadata": safe_metadata(response.get("metadata", {})),
            "rows": rows,
        }
        serialized = json.dumps(payload, indent=2) + "\n"
        if connection_string in serialized:
            raise RuntimeError("Excel XMLA connection string leaked into evidence payload")
        output.write_text(serialized, encoding="utf-8")
        results.append(
            {
                "case_id": case_id,
                "status": "PASS",
                "row_count": len(rows),
                "output": str(output),
            }
        )

    failed = sum(item["status"] == "FAIL" for item in results)
    skipped = sum(item["status"] == "SKIPPED" for item in results)
    return {
        "status": "PASS" if results and failed == 0 else "FAIL",
        "consumer": "excel",
        "security_context": security_context,
        "cube_name": cube_name,
        "case_count": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "skipped": skipped,
        "failed": failed,
        "results": results,
        "truth_boundary": (
            "Captured evidence proves the configured XMLA/MDX model returns the governed case rows. "
            "Credentials/connection strings are never persisted."
        ),
    }


def main() -> int:
    args = parse_args()
    env = dict(os.environ)
    config = resolve_config(
        env,
        runner=args.runner,
        cube_name=args.cube_name,
        connection_string_env=args.connection_string_env,
    )
    errors = validate_request(
        args.manifest,
        config=config,
        security_context=args.security_context,
        max_rows=args.max_rows,
        query_timeout=args.query_timeout,
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
                    args.manifest,
                    evidence_dir=args.evidence_dir,
                    config=config,
                    security_context=args.security_context,
                    max_rows=args.max_rows,
                    query_timeout=args.query_timeout,
                ),
                indent=2,
            )
        )
        return 0

    try:
        report = capture(
            args.manifest,
            args.evidence_dir,
            env=env,
            runner_command=str(config["runner_command"]),
            cube_name=str(config["cube_name"]),
            connection_string_env=args.connection_string_env,
            security_context=args.security_context,
            max_rows=args.max_rows,
            query_timeout=args.query_timeout,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1

    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
