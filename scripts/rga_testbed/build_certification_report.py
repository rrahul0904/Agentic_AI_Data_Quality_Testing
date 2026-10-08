#!/usr/bin/env python3
"""Build a truthful certification summary across local, live-runtime, and consumer evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_PACKAGING_ARTIFACTS = (
    ".github/workflows/production-release.yml",
    "apps/web/Dockerfile",
    "deploy/Dockerfile.api",
    "deploy/k8s/base/kustomization.yaml",
    "deploy/k8s/base/api-deployment.yaml",
    "deploy/k8s/base/web-deployment.yaml",
    "deploy/k8s/base/networkpolicy.yaml",
    "docker-compose.release.yml",
    "docs/PRODUCTION_DEPLOYMENT.md",
    "tests/test_production_deployment_manifests.py",
)


def _repository_packaging_status() -> dict[str, Any]:
    artifacts = [
        {"path": item, "exists": (REPO_ROOT / item).exists()}
        for item in REPOSITORY_PACKAGING_ARTIFACTS
    ]
    missing = [item["path"] for item in artifacts if not item["exists"]]
    return {
        "status": "PASS" if not missing else "INCOMPLETE",
        "required": len(artifacts),
        "present": len(artifacts) - len(missing),
        "missing": missing,
        "artifacts": artifacts,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _consumer_evidence_status(workspace: Path, evidence_dir: Path) -> dict[str, Any]:
    manifest_path = workspace / "release" / "parity" / "parity_manifest.json"
    manifest = _load(manifest_path)
    if not manifest:
        return {
            "status": "UNAVAILABLE",
            "expected": 0,
            "captured": 0,
            "pending": 0,
            "missing": 0,
            "invalid": 0,
            "required_consumers": [],
        }

    expected = 0
    captured = 0
    pending = 0
    missing = 0
    invalid = 0
    for case in manifest.get("cases", []):
        for consumer in manifest.get("required_consumers", []):
            expected += 1
            path = evidence_dir / f"{case['id']}.{consumer}.json"
            if not path.exists():
                missing += 1
                continue
            payload = _load(path)
            if not payload:
                invalid += 1
                continue
            status = payload.get("capture_status")
            rows = payload.get("rows")
            if status == "CAPTURED" and isinstance(rows, list) and rows:
                captured += 1
            elif status == "PENDING":
                pending += 1
            else:
                invalid += 1

    return {
        "status": "COMPLETE" if expected > 0 and captured == expected else "INCOMPLETE",
        "expected": expected,
        "captured": captured,
        "pending": pending,
        "missing": missing,
        "invalid": invalid,
        "required_consumers": manifest.get("required_consumers", []),
    }


def build_report(workspace: Path, evidence_dir: Path | None = None) -> dict[str, Any]:
    evidence_dir = evidence_dir or (workspace / "external-evidence")
    release_path = workspace / "release" / "release_manifest.json"
    live_path = workspace / "evidence" / "certification_manifest.json"
    bounded_path = workspace / "evidence" / "snowflake_demo.json"
    consumer_path = workspace / "evidence" / "cross_consumer_parity.json"
    agent_path = workspace / "evidence" / "agent_smoke.json"
    cdc_path = workspace / "evidence" / "cdc_application.json"
    scale_path = workspace / "evidence" / "scale_test.json"
    workload_path = workspace / "evidence" / "workload_analysis.json"
    optimization_path = workspace / "evidence" / "optimization_analysis_summary.json"
    optimization_diagnostics_path = (
        workspace / "evidence" / "optimization_diagnostics.json"
    )

    release = _load(release_path)
    live = _load(live_path)
    bounded = _load(bounded_path)
    consumer = _load(consumer_path)
    agent = _load(agent_path)
    cdc = _load(cdc_path)
    scale = _load(scale_path)
    workload = _load(workload_path)
    optimization = _load(optimization_path)
    optimization_diagnostics = _load(optimization_diagnostics_path)
    evidence_status = _consumer_evidence_status(workspace, evidence_dir)
    repository_packaging = _repository_packaging_status()

    local_status = "PASS" if release else "MISSING"
    live_status = live.get("status") if live else "PENDING"
    bounded_status = bounded.get("status") if bounded else "PENDING"
    consumer_status = consumer.get("status") if consumer else "PENDING"
    agent_status = agent.get("status") if agent else "PENDING"
    cdc_status = cdc.get("status") if cdc else "PENDING"
    scale_status = scale.get("status") if scale else "PENDING"
    live_optimization = (
        live.get("optimization", {})
        if live and isinstance(live.get("optimization"), dict)
        else {}
    )
    optimization_requested = bool(live_optimization.get("requested"))
    optimization_diagnostics_requested = bool(
        live_optimization.get("diagnostics_requested")
    )
    optimization_status = (
        optimization.get("status")
        if optimization
        else (
            live_optimization.get("status")
            if optimization_requested
            else "NOT_REQUESTED"
        )
    )
    optimization_diagnostics_status = (
        optimization_diagnostics.get("status")
        if optimization_diagnostics
        else (
            live_optimization.get("diagnostics_status")
            if optimization_diagnostics_requested
            else "NOT_REQUESTED"
        )
    )

    blockers: list[str] = []
    if repository_packaging["status"] != "PASS":
        blockers.append("immutable repository deployment packaging is incomplete")
    if not release:
        blockers.append("governed semantic release bundle is missing")
    if live_status != "PASS":
        if bounded_status == "PASS":
            blockers.append(
                "full live Snowflake semantic-runtime certification has not passed; "
                "bounded bootstrap/load/dbt/Semantic View verification evidence has passed"
            )
        else:
            blockers.append("live Snowflake semantic-runtime certification has not passed")
    if consumer_status != "PASS":
        blockers.append("cross-consumer Snowflake/AI/Power BI/Excel parity has not passed")
    if cdc and cdc_status != "PASS":
        blockers.append("CDC correction/late-arrival certification evidence exists but has not passed")
    if scale and scale_status != "PASS":
        blockers.append("local generator/out-of-core scale evidence exists but has not passed")
    if optimization_requested:
        live_acceptance = live.get("acceptance", {}) if live else {}
        if live_acceptance.get("optimization_analysis_pass") is not True:
            blockers.append(
                "requested Snowflake physical-optimization analysis has not passed"
            )
        if (
            optimization_diagnostics_requested
            and live_acceptance.get("optimization_diagnostics_pass") is not True
        ):
            blockers.append(
                "requested read-only optimization diagnostics have not passed"
            )
        if optimization and int(
            optimization.get("executable_physical_mutations", 0)
        ) != 0:
            blockers.append(
                "optimization evidence violated the zero executable physical-mutation invariant"
            )
    if evidence_status["status"] != "COMPLETE":
        blockers.append(
            "consumer evidence is incomplete "
            f"({evidence_status['captured']}/{evidence_status['expected']} captured)"
        )

    repository_scope_complete = bool(
        release and repository_packaging["status"] == "PASS"
    )

    end_to_end_certified = bool(
        release
        and live_status == "PASS"
        and consumer_status == "PASS"
        and evidence_status["status"] == "COMPLETE"
    )

    if end_to_end_certified:
        overall_status = "END_TO_END_CERTIFIED_FOR_EXECUTED_WORKLOAD"
    elif release and live_status == "PASS":
        overall_status = "LIVE_RUNTIME_CERTIFIED_CONSUMER_PARITY_PENDING"
    elif release and bounded_status == "PASS":
        overall_status = "BOUNDED_TARGET_ACCOUNT_CERTIFIED_FULL_RUNTIME_PENDING"
    elif release:
        overall_status = "REPOSITORY_READY_LIVE_CERTIFICATION_PENDING"
    else:
        overall_status = "INCOMPLETE"

    return {
        "certification_report_version": 2,
        "overall_status": overall_status,
        "end_to_end_certified": end_to_end_certified,
        "production_rollout_certified": False,
        "repository_scope_complete": repository_scope_complete,
        "repository_completion_status": (
            "REPOSITORY_SCOPE_COMPLETE_EXTERNAL_CERTIFICATION_DEFERRED"
            if repository_scope_complete
            else "REPOSITORY_SCOPE_INCOMPLETE"
        ),
        "repository_packaging": repository_packaging,
        "deferred_external_certification": [
            "live Snowflake bootstrap/load/dbt/Semantic View target-account evidence",
            "deployed Semantic View and Cortex Agent/MCP runtime evidence",
            "direct-vs-semantic target-account benchmark measurements",
            "governed Power BI/Excel live parity evidence",
            "target-scale SLA evidence",
            "hosted production rollout approval and environment evidence",
        ],
        "workspace": str(workspace),
        "evidence_dir": str(evidence_dir),
        "release": {
            "status": local_status,
            "path": str(release_path),
            "source_sha": release.get("source_sha") if release else None,
            "semantic_manifest_sha256": release.get("semantic_manifest_sha256") if release else None,
            "generated_file_count": release.get("generated_file_count") if release else None,
            "change_status": release.get("change_status") if release else None,
        },
        "bounded_target_account": {
            "status": bounded_status,
            "path": str(bounded_path),
            "scope": bounded.get("scope") if bounded else None,
            "source_sha": bounded.get("source_sha") if bounded else None,
            "semantic_manifest_sha256": (
                bounded.get("semantic_manifest_sha256") if bounded else None
            ),
            "environment": bounded.get("environment") if bounded else None,
            "semantic_deployed": bounded.get("semantic_deployed") if bounded else None,
            "ai_deployed": bounded.get("ai_deployed") if bounded else None,
            "stages": bounded.get("stages") if bounded else None,
            "remaining_external": bounded.get("remaining_external") if bounded else None,
            "production_rollout_certified": (
                bounded.get("production_rollout_certified") if bounded else False
            ),
        },
        "live_runtime": {
            "status": live_status,
            "path": str(live_path),
            "acceptance": live.get("acceptance") if live else None,
            "environment": live.get("environment") if live else None,
        },
        "agent_runtime": {
            "status": agent_status,
            "path": str(agent_path),
            "passed": agent.get("passed") if agent else None,
            "failed": agent.get("failed") if agent else None,
        },
        "change_data": {
            "status": cdc_status,
            "path": str(cdc_path),
            "verify_idempotency": cdc.get("verify_idempotency") if cdc else None,
            "source_event_count": cdc.get("source_event_count") if cdc else None,
        },
        "scale_validation": {
            "status": scale_status,
            "path": str(scale_path),
            "policies": scale.get("policies") if scale else None,
            "total_rows": (
                scale.get("generation", {}).get("total_rows")
                if scale
                else None
            ),
            "peak_rss_mb": (
                scale.get("generation", {}).get("peak_rss_mb")
                if scale
                else None
            ),
            "validation_engine": (
                scale.get("validation", {}).get("engine")
                if scale
                else None
            ),
            "parquet_status": (
                scale.get("parquet", {}).get("status")
                if scale and isinstance(scale.get("parquet"), dict)
                else None
            ),
            "truth_boundary": (
                scale.get("truth_boundary")
                if scale
                else "No local scale-test evidence has been recorded."
            ),
        },
        "consumer_parity": {
            "status": consumer_status,
            "path": str(consumer_path),
            "failed_cases": consumer.get("failed_cases") if consumer else None,
            "evidence": evidence_status,
        },
        "workload_analysis": {
            "status": workload.get("status") if workload else "PENDING",
            "path": str(workload_path),
            "recommendation_count": len(workload.get("recommendations", [])) if workload else None,
        },
        "optimization": {
            "requested": optimization_requested,
            "diagnostics_requested": optimization_diagnostics_requested,
            "status": optimization_status,
            "path": str(optimization_path),
            "diagnostics_status": optimization_diagnostics_status,
            "diagnostics_path": str(optimization_diagnostics_path),
            "recommendation_count": (
                optimization.get("recommendation_count")
                if optimization
                else live_optimization.get("recommendation_count")
            ),
            "history_experiment_count": (
                optimization.get("history_experiment_count")
                if optimization
                else live_optimization.get("history_experiment_count")
            ),
            "experiment_count": (
                optimization.get("experiment_count")
                if optimization
                else live_optimization.get("experiment_count")
            ),
            "executable_physical_mutations": (
                optimization.get("executable_physical_mutations")
                if optimization
                else live_optimization.get("executable_physical_mutations")
            ),
            "truth_boundary": (
                optimization.get("truth_boundary")
                if optimization
                else live_optimization.get("truth_boundary")
            ),
        },
        "blockers": blockers,
        "production_rollout_blockers": [
            "target-scale SLA/load evidence and organizational operational approval are outside this report"
        ],
        "truth_boundary": (
            "A PASS bounded_target_account status means only the executed bootstrap, RAW load, dbt build, "
            "and server-side Semantic View verification stages in snowflake_demo.json passed for the recorded "
            "target account and exact source/semantic hashes. It does not imply Semantic View deployment, "
            "Cortex Agent/MCP runtime proof, direct-versus-semantic benchmark certification, consumer parity, "
            "target-scale SLA, or production rollout approval. END_TO_END_CERTIFIED_FOR_EXECUTED_WORKLOAD "
            "requires the broader live runtime plus captured consumer evidence and cross-consumer parity."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    evidence = report["consumer_parity"]["evidence"]
    blockers = report["blockers"]
    lines = [
        "# Governed Semantic Platform Certification",
        "",
        f"**Overall status:** {report['overall_status']}",
        f"**End-to-end certified for executed workload:** {'YES' if report['end_to_end_certified'] else 'NO'}",
        f"**Production rollout certified:** {'YES' if report['production_rollout_certified'] else 'NO'}",
        f"**Repository scope complete:** {'YES' if report['repository_scope_complete'] else 'NO'}",
        f"**Repository completion status:** {report['repository_completion_status']}",
        "",
        "## Certification surfaces",
        "",
        f"- Governed release: **{report['release']['status']}**",
        (
            "- Bounded target-account slice: "
            f"**{report['bounded_target_account']['status']}** "
            f"(semantic_deployed={report['bounded_target_account']['semantic_deployed']}, "
            f"ai_deployed={report['bounded_target_account']['ai_deployed']})"
        ),
        f"- Live Snowflake runtime: **{report['live_runtime']['status']}**",
        f"- Cortex Agent runtime: **{report['agent_runtime']['status']}**",
        f"- CDC correction/late-arrival cycle: **{report['change_data']['status']}**",
        (
            "- Local generator/out-of-core scale: "
            f"**{report['scale_validation']['status']}** "
            f"(policies={report['scale_validation']['policies']}, "
            f"rows={report['scale_validation']['total_rows']}, "
            f"peak_rss_mb={report['scale_validation']['peak_rss_mb']}, "
            f"parquet={report['scale_validation']['parquet_status']})"
        ),
        f"- Cross-consumer parity: **{report['consumer_parity']['status']}**",
        (
            "- Consumer evidence: "
            f"**{evidence['captured']}/{evidence['expected']} CAPTURED** "
            f"(pending={evidence['pending']}, missing={evidence['missing']}, invalid={evidence['invalid']})"
        ),
        f"- Workload analysis: **{report['workload_analysis']['status']}**",
        (
            "- Physical optimization analysis: "
            f"**{report['optimization']['status']}** "
            f"(requested={report['optimization']['requested']}, "
            f"diagnostics={report['optimization']['diagnostics_status']}, "
            f"experiments={report['optimization']['experiment_count']}, "
            f"executable_mutations={report['optimization']['executable_physical_mutations']})"
        ),
        "",
        "## Current blockers",
        "",
    ]
    if blockers:
        lines.extend(f"- {item}" for item in blockers)
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Truth boundary",
            "",
            report["truth_boundary"],
            "",
        ]
    )
    return "\n".join(lines)


def generate(
    workspace: Path,
    *,
    evidence_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    report = build_report(workspace, evidence_dir)
    output_dir = output_dir or (workspace / "evidence" / "report")
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "certification_summary.json"
    markdown_path = output_dir / "CERTIFICATION_SUMMARY.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {
        "status": "PASS",
        "overall_status": report["overall_status"],
        "end_to_end_certified": report["end_to_end_certified"],
        "production_rollout_certified": report["production_rollout_certified"],
        "repository_scope_complete": report["repository_scope_complete"],
        "repository_completion_status": report["repository_completion_status"],
        "json": str(json_path),
        "markdown": str(markdown_path),
        "blockers": report["blockers"],
    }


def main() -> int:
    args = parse_args()
    result = generate(
        args.workspace,
        evidence_dir=args.evidence_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
