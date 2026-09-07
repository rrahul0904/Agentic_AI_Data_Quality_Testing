"""Deterministic dbt completion validators aligned to the pinned Altimate reference."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import sqlglot


@dataclass(frozen=True)
class ValidatorResult:
    name: str
    ok: bool
    verdict: str
    reason: str | None = None
    fix_hint: str | None = None
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _target(project_dir: str | Path) -> Path:
    return Path(project_dir).expanduser().resolve() / "target"


def _nodes(manifest: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not manifest:
        return {}
    return {
        **manifest.get("nodes", {}),
        **manifest.get("sources", {}),
    }


def validate_build_green(
    project_dir: str | Path,
    *,
    touched_models: Iterable[str] = (),
    session_start_epoch: float | None = None,
) -> ValidatorResult:
    target = _target(project_dir)
    run_path = target / "run_results.json"
    artifact = _load(run_path)
    touched = tuple(touched_models)
    if artifact is None:
        if touched:
            return ValidatorResult(
                "dbt-build-green", False, "no-fresh-build",
                f"{len(touched)} touched model(s) have no run_results.json build evidence.",
                "Run dbt build for the changed models and verify the resulting artifact.",
                {"models_touched": len(touched), "run_results": str(run_path)},
            )
        return ValidatorResult(
            "dbt-build-green", True, "nothing-to-gate",
            details={"models_touched": 0, "run_results": str(run_path)},
        )

    if session_start_epoch is not None and run_path.stat().st_mtime < session_start_epoch:
        return ValidatorResult(
            "dbt-build-green", not touched, "stale-build" if touched else "nothing-to-gate",
            "The available dbt artifact predates this session." if touched else None,
            "Run dbt build after the edits." if touched else None,
            {"models_touched": len(touched), "run_results_mtime": run_path.stat().st_mtime},
        )

    metadata = artifact.get("metadata", {})
    invocation = str(metadata.get("invocation_id") or "")
    command = str(
        artifact.get("args", {}).get("which")
        or artifact.get("args", {}).get("command")
        or metadata.get("command")
        or ""
    ).casefold()
    if command in {"compile", "parse", "ls"}:
        return ValidatorResult(
            "dbt-build-green", False, "non-executing-artifact",
            f"The fresh artifact came from dbt {command}, which does not prove model execution.",
            "Run dbt build or dbt run for the changed models.",
            {"command": command, "invocation_id": invocation},
        )

    results = artifact.get("results", ())
    model_results = {
        str(item.get("unique_id")): item
        for item in results
        if str(item.get("unique_id", "")).startswith(("model.", "seed.", "snapshot."))
    }
    failures = [
        {
            "unique_id": unique_id,
            "status": item.get("status"),
            "message": item.get("message"),
        }
        for unique_id, item in model_results.items()
        if str(item.get("status", "")).casefold() not in {"success", "pass", "skipped", "warn"}
    ]

    touched_names = {Path(item).stem.casefold() for item in touched}
    covered = {
        str(item.get("unique_id", "")).split(".")[-1].casefold()
        for item in model_results.values()
    }
    missing = sorted(touched_names - covered)
    ok = not failures and not missing
    return ValidatorResult(
        "dbt-build-green",
        ok,
        "fresh-build" if ok else "build-failed-or-uncovered",
        None if ok else "The fresh build contains failures or does not cover every touched model.",
        None if ok else "Fix model errors, rebuild the touched selector, and verify run_results.json.",
        {
            "models_touched": len(touched),
            "model_results": len(model_results),
            "missing_touched_models": missing,
            "failures": failures,
        },
    )


_DELIVERABLE = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_deliverable_names(manifest: Mapping[str, Any]) -> ValidatorResult:
    findings = []
    for unique_id, node in _nodes(manifest).items():
        if node.get("resource_type") not in {"model", "snapshot", "seed"}:
            continue
        name = str(node.get("name") or unique_id.split(".")[-1])
        alias = str(node.get("alias") or name)
        if not _DELIVERABLE.fullmatch(name):
            findings.append({"unique_id": unique_id, "field": "name", "value": name})
        if not _DELIVERABLE.fullmatch(alias):
            findings.append({"unique_id": unique_id, "field": "alias", "value": alias})
    return ValidatorResult(
        "dbt-deliverable-names",
        not findings,
        "valid" if not findings else "invalid-deliverable-names",
        None if not findings else f"{len(findings)} dbt deliverable naming violation(s) found.",
        None if not findings else "Use lowercase snake_case dbt model/alias names.",
        {"findings": findings},
    )


def validate_dialect(
    manifest: Mapping[str, Any],
    *,
    dialect: str,
) -> ValidatorResult:
    errors = []
    reviewed = 0
    for unique_id, node in _nodes(manifest).items():
        if node.get("resource_type") != "model":
            continue
        sql = node.get("compiled_code") or node.get("compiled_sql")
        if not sql:
            continue
        reviewed += 1
        try:
            sqlglot.parse(sql, read=dialect)
        except sqlglot.errors.SqlglotError as exc:
            errors.append({"unique_id": unique_id, "error": str(exc)})
    return ValidatorResult(
        "dbt-dialect-guard",
        not errors,
        "parseable" if not errors else "dialect-errors",
        None if not errors else f"{len(errors)} compiled dbt model(s) fail {dialect} parsing.",
        None if not errors else "Fix dialect-incompatible compiled SQL before completion.",
        {"dialect": dialect, "models_reviewed": reviewed, "errors": errors},
    )


def validate_incremental_config(manifest: Mapping[str, Any]) -> ValidatorResult:
    findings = []
    for unique_id, node in _nodes(manifest).items():
        if node.get("resource_type") != "model":
            continue
        config = node.get("config") or {}
        if config.get("materialized") != "incremental":
            continue
        unique_key = config.get("unique_key")
        strategy = config.get("incremental_strategy")
        if not unique_key:
            findings.append({"unique_id": unique_id, "issue": "missing_unique_key"})
        if strategy in {"merge", "delete+insert"} and not unique_key:
            findings.append({
                "unique_id": unique_id,
                "issue": "strategy_requires_unique_key",
                "strategy": strategy,
            })
    return ValidatorResult(
        "dbt-incremental-config",
        not findings,
        "valid" if not findings else "unsafe-incremental-config",
        None if not findings else f"{len(findings)} incremental configuration issue(s) found.",
        None if not findings else "Add a deterministic unique_key or use an appropriate append strategy.",
        {"findings": findings},
    )


def validate_nothing_built(
    project_dir: str | Path,
    *,
    task_requires_build: bool,
) -> ValidatorResult:
    target = _target(project_dir)
    run_results = _load(target / "run_results.json")
    run_dir = target / "run"
    has_run_outputs = run_dir.is_dir() and any(path.is_file() for path in run_dir.rglob("*"))
    has_results = bool(run_results and run_results.get("results"))
    ok = not task_requires_build or has_results or has_run_outputs
    return ValidatorResult(
        "dbt-nothing-built",
        ok,
        "build-evidence-present" if ok else "nothing-built",
        None if ok else "The task requires executable dbt output but no build evidence exists.",
        None if ok else "Run dbt build/run for the requested selector and verify artifacts.",
        {
            "task_requires_build": task_requires_build,
            "run_results_present": has_results,
            "run_outputs_present": has_run_outputs,
        },
    )


def validate_schema(
    manifest: Mapping[str, Any],
    catalog: Mapping[str, Any] | None,
) -> ValidatorResult:
    catalog_nodes = {
        **((catalog or {}).get("nodes") or {}),
        **((catalog or {}).get("sources") or {}),
    }
    findings = []
    checked = 0
    for unique_id, node in _nodes(manifest).items():
        if node.get("resource_type") != "model":
            continue
        declared = {
            str(name).casefold(): str((metadata or {}).get("data_type") or "").casefold()
            for name, metadata in (node.get("columns") or {}).items()
        }
        actual_node = catalog_nodes.get(unique_id) or {}
        actual = {
            str(name).casefold(): str((metadata or {}).get("type") or "").casefold()
            for name, metadata in (actual_node.get("columns") or {}).items()
        }
        if not declared or not actual:
            continue
        checked += 1
        missing = sorted(set(declared) - set(actual))
        extra = sorted(set(actual) - set(declared))
        type_mismatches = [
            {
                "column": column,
                "declared": declared[column],
                "actual": actual[column],
            }
            for column in sorted(set(declared) & set(actual))
            if declared[column] and actual[column] and declared[column] != actual[column]
        ]
        if missing or extra or type_mismatches:
            findings.append({
                "unique_id": unique_id,
                "missing": missing,
                "extra": extra,
                "type_mismatches": type_mismatches,
            })
    return ValidatorResult(
        "dbt-schema-verify",
        not findings,
        "verified" if not findings and checked else "inconclusive" if not checked else "schema-mismatch",
        None if not findings else f"{len(findings)} model schema mismatch(es) found.",
        None if not findings else "Update model SQL/YAML so declared and built schemas agree.",
        {"models_checked": checked, "findings": findings},
    )


def validate_tests_pass(run_results: Mapping[str, Any] | None) -> ValidatorResult:
    if not run_results:
        return ValidatorResult(
            "dbt-tests-pass",
            True,
            "nothing-to-gate",
            details={"tests_checked": 0},
        )
    test_rows = [
        item
        for item in run_results.get("results", ())
        if str(item.get("unique_id", "")).startswith("test.")
    ]
    failures = [
        {
            "unique_id": item.get("unique_id"),
            "status": item.get("status"),
            "message": item.get("message"),
            "failures": item.get("failures"),
        }
        for item in test_rows
        if str(item.get("status", "")).casefold() not in {"pass", "success", "warn", "skipped"}
    ]
    return ValidatorResult(
        "dbt-tests-pass",
        not failures,
        "tests-pass" if not failures and test_rows else "nothing-to-gate" if not test_rows else "tests-failed",
        None if not failures else f"{len(failures)} dbt test(s) failed.",
        None if not failures else "Fix model logic or data-quality defects, rerun dbt test, and verify run_results.",
        {"tests_checked": len(test_rows), "failures": failures},
    )


def run_validators(
    project_dir: str | Path,
    *,
    manifest: Mapping[str, Any] | None = None,
    catalog: Mapping[str, Any] | None = None,
    run_results: Mapping[str, Any] | None = None,
    dialect: str = "snowflake",
    touched_models: Iterable[str] = (),
    session_start_epoch: float | None = None,
    task_requires_build: bool = False,
) -> dict[str, Any]:
    root = Path(project_dir).expanduser().resolve()
    manifest_value = dict(manifest or _load(root / "target" / "manifest.json") or {})
    catalog_value = dict(catalog or _load(root / "target" / "catalog.json") or {})
    results_value = dict(run_results or _load(root / "target" / "run_results.json") or {})
    results = [
        validate_build_green(root, touched_models=touched_models, session_start_epoch=session_start_epoch),
        validate_deliverable_names(manifest_value),
        validate_dialect(manifest_value, dialect=dialect),
        validate_incremental_config(manifest_value),
        validate_nothing_built(root, task_requires_build=task_requires_build),
        validate_schema(manifest_value, catalog_value),
        validate_tests_pass(results_value),
    ]
    return {
        "status": "PASS" if all(result.ok for result in results) else "FAIL",
        "validators": [result.as_dict() for result in results],
        "blocking": [result.name for result in results if not result.ok],
    }
