#!/usr/bin/env python3
"""Build a truthful certification summary across local, live-runtime, and consumer evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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
    consumer_path = workspace / "evidence" / "cross_consumer_parity.json"
    agent_path = workspace / "evidence" / "agent_smoke.json"
    cdc_path = workspace / "evidence" / "cdc_application.json"
    scale_path = workspace / "evidence" / "scale_test.json"
    workload_path = workspace / "evidence" / "workload_analysis.json"

    release = _load(release_path)
    live = _load(live_path)
    consumer = _load(consumer_path)
    agent = _load(agent_path)
    cdc = _load(cdc_path)
    scale = _load(scale_path)
    workload = _load(workload_path)
    evidence_status = _consumer_evidence_status(workspace, evidence_dir)

    local_status = "PASS" if release else "MISSING"
    live_status = live.get("status") if live else "PENDING"
    consumer_status = consumer.get("status") if consumer else "PENDING"
    agent_status = agent.get("status") if agent else "PENDING"
    cdc_status = cdc.get("status") if cdc else "PENDING"
    scale_status = scale.get("status") if scale else "PENDING"

    blockers: list[str] = []
    if not release:
        blockers.append("governed semantic release bundle is missing")
    if live_status != "PASS":
        blockers.append("live Snowflake semantic-runtime certification has not passed")
    if consumer_status != "PASS":
        blockers.append("cross-consumer Snowflake/AI/Power BI/Excel parity has not passed")
    if cdc and cdc_status != "PASS":
        blockers.append("CDC correction/late-arrival certification evidence exists but has not passed")
    if scale and scale_status != "PASS":
        blockers.append("local generator/out-of-core scale evidence exists but has not passed")
    if evidence_status["status"] != "COMPLETE":
        blockers.append(
            "consumer evidence is incomplete "
            f"({evidence_status['captured']}/{evidence_status['expected']} captured)"
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
    elif release:
        overall_status = "REPOSITORY_READY_LIVE_CERTIFICATION_PENDING"
    else:
        overall_status = "INCOMPLETE"

    return {
        "certification_report_version": 1,
        "overall_status": overall_status,
        "end_to_end_certified": end_to_end_certified,
        "production_rollout_certified": False,
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
        "blockers": blockers,
        "production_rollout_blockers": [
            "target-scale SLA/load evidence and organizational operational approval are outside this report"
        ],
        "truth_boundary": (
            "END_TO_END_CERTIFIED_FOR_EXECUTED_WORKLOAD means the governed release, live Snowflake runtime, "
            "captured consumer evidence, and cross-consumer parity passed for the executed workload/environment. "
            "It does not by itself certify a production rollout."
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
        "",
        "## Certification surfaces",
        "",
        f"- Governed release: **{report['release']['status']}**",
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
