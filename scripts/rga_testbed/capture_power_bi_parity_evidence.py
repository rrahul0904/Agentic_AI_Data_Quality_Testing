#!/usr/bin/env python3
"""Capture governed Power BI parity evidence through Execute DAX Queries."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

POWER_BI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
POWER_BI_API = "https://api.powerbi.com/v1.0/myorg"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--workspace-id")
    parser.add_argument("--dataset-id")
    parser.add_argument("--security-context", required=True)
    parser.add_argument("--effective-username")
    parser.add_argument("--role", action="append", default=[])
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


def resolve_config(
    env: dict[str, str],
    *,
    workspace_id: str | None,
    dataset_id: str | None,
) -> dict[str, Any]:
    workspace = workspace_id or env.get("POWER_BI_WORKSPACE_ID")
    dataset = dataset_id or env.get("POWER_BI_DATASET_ID")
    direct_token = bool(env.get("POWER_BI_ACCESS_TOKEN"))
    client_credentials = all(
        env.get(name)
        for name in (
            "POWER_BI_TENANT_ID",
            "POWER_BI_CLIENT_ID",
            "POWER_BI_CLIENT_SECRET",
        )
    )
    return {
        "workspace_id": workspace,
        "dataset_id": dataset,
        "auth_mode": (
            "access_token"
            if direct_token
            else ("client_credentials" if client_credentials else None)
        ),
        "auth_configured": direct_token or client_credentials,
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
        if not config.get("workspace_id"):
            errors.append(
                "Power BI workspace id is required via --workspace-id or POWER_BI_WORKSPACE_ID"
            )
        if not config.get("dataset_id"):
            errors.append(
                "Power BI dataset id is required via --dataset-id or POWER_BI_DATASET_ID"
            )
        if not config.get("auth_configured"):
            errors.append(
                "Power BI authentication is required via POWER_BI_ACCESS_TOKEN or "
                "POWER_BI_TENANT_ID/POWER_BI_CLIENT_ID/POWER_BI_CLIENT_SECRET"
            )
        if not confirm:
            errors.append("Refusing live Power BI evidence capture without --confirm")
    return errors


def power_bi_url(workspace_id: str, dataset_id: str) -> str:
    return (
        f"{POWER_BI_API}/groups/{workspace_id}/datasets/{dataset_id}"
        "/executeDaxQueries"
    )


def acquire_access_token(env: dict[str, str]) -> tuple[str, str]:
    token = env.get("POWER_BI_ACCESS_TOKEN")
    if token:
        return token, "access_token"

    tenant = env.get("POWER_BI_TENANT_ID")
    client_id = env.get("POWER_BI_CLIENT_ID")
    client_secret = env.get("POWER_BI_CLIENT_SECRET")
    if not (tenant and client_id and client_secret):
        raise ValueError("Power BI authentication is not configured")

    token_url = (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    )
    body = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": POWER_BI_SCOPE,
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    request = Request(
        token_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Power BI Entra token request failed ({exc.code}): {detail}"
        ) from exc
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Power BI Entra token response did not contain access_token")
    return str(token), "client_credentials"


def build_request_body(
    dax: str,
    *,
    max_rows: int,
    query_timeout: int,
    effective_username: str | None,
    roles: list[str],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "query": dax,
        "queryTimeout": query_timeout,
        "resultSetRowCountLimit": max_rows,
        "schemaOnly": False,
    }
    if effective_username:
        body["effectiveUsername"] = effective_username
    if roles:
        body["roles"] = roles
    return body


def execute_dax(
    *,
    url: str,
    token: str,
    body: dict[str, Any],
) -> bytes:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.apache.arrow.stream",
        },
    )
    try:
        with urlopen(request, timeout=max(30, int(body["queryTimeout"]) + 15)) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Power BI Execute DAX Queries failed ({exc.code}): {detail}"
        ) from exc


def _schema_metadata(schema: Any) -> dict[str, str]:
    return {
        key.decode("utf-8", errors="replace"): value.decode(
            "utf-8", errors="replace"
        )
        for key, value in (schema.metadata or {}).items()
    }


def decode_arrow_rows(content: bytes) -> list[dict[str, Any]]:
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required for Power BI Arrow evidence capture; "
            "install the project testbed extra"
        ) from exc

    stream = io.BytesIO(content)
    rows: list[dict[str, Any]] = []
    while stream.tell() < len(content):
        position = stream.tell()
        try:
            reader = pa.ipc.open_stream(stream)
            table = reader.read_all()
        except pa.ArrowInvalid:
            if stream.tell() == position:
                break
            continue
        metadata = _schema_metadata(reader.schema)
        if metadata.get("IsError", "").lower() == "true":
            raise RuntimeError(
                "Power BI DAX query error "
                f"[{metadata.get('FaultCode')}]: "
                f"{metadata.get('FaultString')}"
            )
        rows.extend(table.to_pylist())
        if stream.tell() <= position:
            break
    return rows


def normalize_power_bi_column(name: str) -> str:
    value = str(name).strip()
    if "[" in value and value.endswith("]"):
        value = value.rsplit("[", 1)[1][:-1]
    return value.strip("[]").upper()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "as_py"):
        return _jsonable(value.as_py())
    return str(value)


def normalize_rows(
    rows: list[dict[str, Any]],
    expected_columns: list[str],
) -> list[dict[str, Any]]:
    if not rows:
        raise ValueError("Power BI query returned no rows")
    expected = [str(name).upper() for name in expected_columns]
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        upper: dict[str, Any] = {}
        for key, value in row.items():
            normalized_key = normalize_power_bi_column(str(key))
            if normalized_key in upper:
                raise ValueError(
                    f"row {index} has duplicate normalized column {normalized_key}"
                )
            upper[normalized_key] = _jsonable(value)
        if sorted(upper) != sorted(expected):
            raise ValueError(
                f"row {index} column mismatch: expected {expected}, "
                f"got {sorted(upper)}"
            )
        normalized.append({column: upper[column] for column in expected})
    return normalized


def plan(
    manifest_path: Path,
    *,
    evidence_dir: Path,
    config: dict[str, Any],
    security_context: str,
    effective_username: str | None,
    roles: list[str],
    max_rows: int,
    query_timeout: int,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    cases: list[dict[str, Any]] = []
    for case in manifest.get("cases", []):
        dax_file = case.get("power_bi", {}).get("dax_file")
        path = manifest_path.parent / str(dax_file) if dax_file else None
        cases.append(
            {
                "case_id": case.get("id"),
                "dax_file": str(path) if path else None,
                "dax_exists": bool(path and path.exists()),
                "output": str(
                    evidence_dir / f"{case.get('id')}.power_bi.json"
                ),
                "expected_columns": (
                    case.get("dimensions", []) + case.get("metrics", [])
                ),
            }
        )
    return {
        "status": "DRY_RUN",
        "manifest": str(manifest_path),
        "evidence_dir": str(evidence_dir),
        "workspace_id": config.get("workspace_id"),
        "dataset_id": config.get("dataset_id"),
        "auth_mode": config.get("auth_mode"),
        "security_context": security_context,
        "effective_username": effective_username,
        "roles": roles,
        "max_rows": max_rows,
        "query_timeout": query_timeout,
        "case_count": len(cases),
        "cases": cases,
        "api": "Power BI Execute DAX Queries (Apache Arrow)",
        "truth_boundary": (
            "This path certifies Power BI semantic-model query results only when the "
            "target dataset supports Execute DAX Queries. Excel remains a separate "
            "governed/XMLA evidence surface."
        ),
    }


def capture(
    manifest_path: Path,
    evidence_dir: Path,
    *,
    env: dict[str, str],
    workspace_id: str,
    dataset_id: str,
    security_context: str,
    effective_username: str | None,
    roles: list[str],
    max_rows: int,
    query_timeout: int,
    overwrite: bool,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    token, auth_mode = acquire_access_token(env)
    url = power_bi_url(workspace_id, dataset_id)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for case in manifest.get("cases", []):
        case_id = str(case["id"])
        output = evidence_dir / f"{case_id}.power_bi.json"
        if output.exists() and not overwrite:
            existing = load_json(output)
            if existing.get("capture_status") == "CAPTURED":
                results.append(
                    {
                        "case_id": case_id,
                        "status": "SKIPPED",
                        "error": (
                            "captured evidence already exists; use --overwrite "
                            "to replace it"
                        ),
                        "output": str(output),
                    }
                )
                continue

        dax_file = case.get("power_bi", {}).get("dax_file")
        if not dax_file:
            results.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "error": "parity case does not define power_bi.dax_file",
                    "output": str(output),
                }
            )
            continue
        dax_path = manifest_path.parent / str(dax_file)
        if not dax_path.exists():
            results.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "error": f"DAX file not found: {dax_path}",
                    "output": str(output),
                }
            )
            continue

        dax = dax_path.read_text(encoding="utf-8")
        try:
            content = execute_dax(
                url=url,
                token=token,
                body=build_request_body(
                    dax,
                    max_rows=max_rows,
                    query_timeout=query_timeout,
                    effective_username=effective_username,
                    roles=roles,
                ),
            )
            rows = normalize_rows(
                decode_arrow_rows(content),
                case.get("dimensions", []) + case.get("metrics", []),
            )
            if (
                not rows
                and not case.get("acceptance", {}).get(
                    "allow_empty_result", False
                )
            ):
                raise ValueError("Power BI evidence rows must not be empty")
        except Exception as exc:
            results.append(
                {
                    "case_id": case_id,
                    "status": "FAIL",
                    "error": str(exc),
                    "output": str(output),
                }
            )
            continue

        payload = {
            "case_id": case_id,
            "business_question": case.get("business_question"),
            "consumer": "power_bi",
            "security_context": security_context,
            "capture_status": "CAPTURED",
            "capture_method": "power_bi_execute_dax_queries_arrow",
            "workspace_id": workspace_id,
            "dataset_id": dataset_id,
            "effective_username": effective_username,
            "roles": roles,
            "auth_mode": auth_mode,
            "dax_file": str(dax_path),
            "dax_sha256": hashlib.sha256(dax.encode("utf-8")).hexdigest(),
            "rows": rows,
        }
        output.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        results.append(
            {
                "case_id": case_id,
                "status": "PASS",
                "row_count": len(rows),
                "output": str(output),
            }
        )

    failed = sum(item["status"] == "FAIL" for item in results)
    return {
        "status": "PASS" if results and failed == 0 else "FAIL",
        "consumer": "power_bi",
        "security_context": security_context,
        "workspace_id": workspace_id,
        "dataset_id": dataset_id,
        "auth_mode": auth_mode,
        "case_count": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "skipped": sum(item["status"] == "SKIPPED" for item in results),
        "failed": failed,
        "results": results,
        "truth_boundary": (
            "Power BI API evidence does not certify Excel. It also does not prove "
            "that an unsupported live-connected dataset can use Execute DAX Queries."
        ),
    }


def main() -> int:
    args = parse_args()
    env = dict(os.environ)
    config = resolve_config(
        env,
        workspace_id=args.workspace_id,
        dataset_id=args.dataset_id,
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
        try:
            result = plan(
                args.manifest,
                evidence_dir=args.evidence_dir,
                config=config,
                security_context=args.security_context,
                effective_username=args.effective_username,
                roles=args.role,
                max_rows=args.max_rows,
                query_timeout=args.query_timeout,
            )
        except Exception as exc:
            print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0

    try:
        result = capture(
            args.manifest,
            args.evidence_dir,
            env=env,
            workspace_id=str(config["workspace_id"]),
            dataset_id=str(config["dataset_id"]),
            security_context=args.security_context,
            effective_username=args.effective_username,
            roles=args.role,
            max_rows=args.max_rows,
            query_timeout=args.query_timeout,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
