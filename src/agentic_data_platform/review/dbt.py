"""Deterministic dbt pull/merge request review engine."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph
from agentic_data_platform.dbt.validators import run_validators
from agentic_data_platform.governance import classify_column
from agentic_data_platform.sql.intelligence import review_sql


_BLOCKING_SEVERITIES = {"ERROR", "CRITICAL", "HIGH"}
_BLOCKING_SQL_RULES = {
    "DANGEROUS_DDL",
    "DROP_TRUNCATE",
    "DELETE_WITHOUT_WHERE",
    "UPDATE_WITHOUT_WHERE",
    "MERGE_RISK",
}


def _git_changed_files(
    repository: Path,
    *,
    base: str = "origin/main",
    head: str = "HEAD",
) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "git diff failed: " + (completed.stderr or completed.stdout)[-2000:]
        )
    return sorted(
        {
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip()
        }
    )


def _model_for_path(
    graph: DbtManifestGraph,
    path: str,
) -> tuple[str, dict[str, Any]] | None:
    normalized = Path(path).as_posix()
    matches = []
    for node_id, node in graph.nodes.items():
        if node.get("resource_type") != "model":
            continue
        candidate = str(
            node.get("original_file_path")
            or node.get("path")
            or ""
        )
        if candidate == normalized or candidate.endswith(normalized) or normalized.endswith(candidate):
            matches.append((node_id, node))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous changed dbt path {path}: "
            + ", ".join(node_id for node_id, _ in matches)
        )
    return None


def _severity(finding: Mapping[str, Any]) -> str:
    return str(finding.get("severity") or "").upper()


def _sql_blocking(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in findings
        if _severity(item) in _BLOCKING_SEVERITIES
        or str(item.get("rule_id") or "").upper() in _BLOCKING_SQL_RULES
    ]


def review_dbt_changes(
    project_dir: str | Path,
    *,
    target_dir: str | Path | None = None,
    repository: str | Path | None = None,
    changed_files: Iterable[str] | None = None,
    base: str = "origin/main",
    head: str = "HEAD",
    previous_manifest: Mapping[str, Any] | None = None,
    dialect: str = "snowflake",
) -> dict[str, Any]:
    project = Path(project_dir).expanduser().resolve()
    target = (
        Path(target_dir).expanduser().resolve()
        if target_dir
        else project / "target"
    )
    artifacts = DbtArtifacts.load(target)
    graph = DbtManifestGraph(artifacts)

    files = (
        sorted({str(item) for item in changed_files})
        if changed_files is not None
        else _git_changed_files(
            Path(repository or project).expanduser().resolve(),
            base=base,
            head=head,
        )
    )
    dbt_files = [
        path for path in files
        if path.endswith((".sql", ".yml", ".yaml"))
        and (
            "/models/" in "/" + path
            or path.startswith("models/")
            or "/snapshots/" in "/" + path
            or path.startswith("snapshots/")
        )
    ]

    changed_models: list[dict[str, Any]] = []
    unresolved_files: list[str] = []
    sql_findings: list[dict[str, Any]] = []
    impacts: list[dict[str, Any]] = []
    test_gaps: list[dict[str, Any]] = []
    pii_findings: list[dict[str, Any]] = []

    for path in dbt_files:
        if not path.endswith(".sql"):
            continue
        resolved = _model_for_path(graph, path)
        if resolved is None:
            unresolved_files.append(path)
            continue
        node_id, node = resolved
        changed_models.append(
            {
                "unique_id": node_id,
                "name": node.get("name"),
                "path": path,
                "materialized": (node.get("config") or {}).get("materialized"),
            }
        )
        compiled = str(
            node.get("compiled_code")
            or node.get("compiled_sql")
            or node.get("raw_code")
            or node.get("raw_sql")
            or ""
        )
        if compiled:
            result = review_sql(compiled, dialect)
            for finding in result.get("findings", ()):
                sql_findings.append(
                    {
                        "model": node_id,
                        "path": path,
                        **dict(finding),
                    }
                )
        impact = graph.impact(node_id)
        impacts.append(impact)
        tests = graph.tests_for_node(node_id)
        if not tests:
            test_gaps.append(
                {
                    "model": node_id,
                    "path": path,
                    "recommended_selector": impact["recommended_selector"],
                }
            )
        for column_name, metadata in (node.get("columns") or {}).items():
            for finding in classify_column(
                str(column_name),
                data_type=str((metadata or {}).get("data_type") or ""),
                description=(metadata or {}).get("description"),
                tags=(metadata or {}).get("tags") or (),
            ):
                if float(finding["confidence"]) >= 0.8:
                    pii_findings.append(
                        {
                            "model": node_id,
                            "column": column_name,
                            **finding,
                        }
                    )

    touched_models = [item["path"] for item in changed_models]
    validators = run_validators(
        project,
        manifest=artifacts.manifest,
        catalog=artifacts.catalog,
        run_results=artifacts.run_results,
        dialect=dialect,
        touched_models=touched_models,
        task_requires_build=bool(changed_models),
    )
    failed_tests = graph.failed_tests()

    state_impact = None
    if previous_manifest:
        state_impact = graph.modified_impact(dict(previous_manifest))

    blockers: list[dict[str, Any]] = []
    for name in validators.get("blocking", ()):
        blockers.append({"type": "validator", "name": name})
    blockers.extend(
        {
            "type": "sql",
            "model": item.get("model"),
            "rule_id": item.get("rule_id"),
            "message": item.get("message"),
        }
        for item in _sql_blocking(sql_findings)
    )
    blockers.extend(
        {
            "type": "dbt_test",
            "unique_id": item.get("unique_id"),
            "message": item.get("message"),
        }
        for item in failed_tests
    )
    blockers.extend(
        {"type": "unresolved_changed_file", "path": path}
        for path in unresolved_files
    )

    comments: list[dict[str, Any]] = []
    comments.extend({"type": "test_gap", **item} for item in test_gaps)
    comments.extend(
        {
            "type": "pii",
            "model": item["model"],
            "column": item["column"],
            "category": item["category"],
            "confidence": item["confidence"],
        }
        for item in pii_findings
    )
    comments.extend(
        {
            "type": "impact",
            "model": item["changed_asset"]["unique_id"],
            "severity": item["severity"],
            "downstream_count": len(item["transitive_downstream"]),
        }
        for item in impacts
        if item["severity"] in {"MEDIUM", "HIGH"}
    )

    if blockers:
        verdict = "REQUEST_CHANGES"
    elif comments:
        verdict = "COMMENT"
    else:
        verdict = "APPROVE"

    evidence = {
        "changed_files": files,
        "dbt_files": dbt_files,
        "changed_models": changed_models,
        "unresolved_files": unresolved_files,
        "validators": validators,
        "failed_tests": failed_tests,
        "sql_findings": sql_findings,
        "impacts": impacts,
        "test_gaps": test_gaps,
        "pii_findings": pii_findings,
        "state_impact": state_impact,
    }
    signature_payload = json.dumps(
        {
            "verdict": verdict,
            "blockers": blockers,
            "comments": comments,
            "evidence": evidence,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    signature = hashlib.sha256(signature_payload.encode()).hexdigest()
    return {
        "status": "PASS",
        "verdict": verdict,
        "signature": signature,
        "blockers": blockers,
        "comments": comments,
        "evidence": evidence,
        "deterministic": True,
        "llm_blocking_decision": False,
    }


def format_review_body(review: Mapping[str, Any]) -> str:
    lines = [
        "## Agentic Data Engineering deterministic dbt review",
        "",
        f"Verdict: {review['verdict']}",
        f"Signature: {review['signature']}",
        "",
    ]
    blockers = list(review.get("blockers") or ())
    comments = list(review.get("comments") or ())
    if blockers:
        lines += ["### Blocking findings", ""]
        for item in blockers:
            lines.append("- " + json.dumps(item, sort_keys=True, default=str))
        lines.append("")
    if comments:
        lines += ["### Review comments", ""]
        for item in comments[:50]:
            lines.append("- " + json.dumps(item, sort_keys=True, default=str))
        lines.append("")
    evidence = review.get("evidence", {})
    lines += [
        "### Evidence",
        "",
        f"- Changed dbt models: {len(evidence.get('changed_models', ())) }",
        f"- Validators blocking: {len(evidence.get('validators', {}).get('blocking', ())) }",
        f"- Failed dbt tests: {len(evidence.get('failed_tests', ())) }",
        f"- SQL findings: {len(evidence.get('sql_findings', ())) }",
        "",
        "This verdict is produced by deterministic validators and tools; an LLM does not decide blocking status.",
    ]
    return "\n".join(lines)


def change_impact(review: Mapping[str, Any]) -> dict[str, Any]:
    impacts = list(review.get("evidence", {}).get("impacts", ()))
    return {
        "status": "PASS",
        "changed_models": review.get("evidence", {}).get("changed_models", ()),
        "impacts": impacts,
        "affected_assets": sum(
            len(item.get("transitive_downstream", ())) for item in impacts
        ),
        "highest_severity": (
            "HIGH"
            if any(item.get("severity") == "HIGH" for item in impacts)
            else "MEDIUM"
            if any(item.get("severity") == "MEDIUM" for item in impacts)
            else "LOW"
        ),
        "review_signature": review.get("signature"),
    }


def recommended_tests(review: Mapping[str, Any]) -> dict[str, Any]:
    selectors = sorted(
        {
            str(item.get("recommended_selector"))
            for item in review.get("evidence", {}).get("test_gaps", ())
            if item.get("recommended_selector")
        }
    )
    impacted_tests = sorted(
        {
            str(test.get("unique_id"))
            for impact in review.get("evidence", {}).get("impacts", ())
            for test in impact.get("affected_tests", ())
            if test.get("unique_id")
        }
    )
    return {
        "status": "PASS",
        "selectors": selectors,
        "affected_tests": impacted_tests,
        "review_signature": review.get("signature"),
    }


def deployment_risk(review: Mapping[str, Any]) -> dict[str, Any]:
    blockers = list(review.get("blockers") or ())
    impacts = list(review.get("evidence", {}).get("impacts", ()))
    failed_tests = list(review.get("evidence", {}).get("failed_tests", ()))
    if blockers or failed_tests:
        risk = "HIGH"
    elif any(item.get("severity") == "HIGH" for item in impacts):
        risk = "HIGH"
    elif review.get("comments"):
        risk = "MEDIUM"
    else:
        risk = "LOW"
    return {
        "status": "PASS",
        "risk": risk,
        "verdict": review.get("verdict"),
        "blocker_count": len(blockers),
        "comment_count": len(review.get("comments") or ()),
        "changed_model_count": len(
            review.get("evidence", {}).get("changed_models", ())
        ),
        "review_signature": review.get("signature"),
    }
