"""Cross-system root-cause and health scoring using deterministic evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph
from agentic_data_platform.platform.airflow import AirflowProject
from agentic_data_platform.platform.airflow_ops import pipeline_health
from agentic_data_platform.platform.discovery import PlatformDiscovery
from agentic_data_platform.platform.graph import PlatformAssetGraph
from agentic_data_platform.quality.store import SQLiteQualityStore


def platform_root_cause(project: str | Path, quality_database: str | Path, *, asset: str | None = None) -> dict[str, Any]:
    root = Path(project)
    quality = SQLiteQualityStore(quality_database)
    quality.initialize()
    health = PlatformDiscovery(root).health()
    airflow = AirflowProject.scan(root).failure_summary()
    dbt = DbtManifestGraph(DbtArtifacts.load(root / "dbt" / "target"))
    failed_tests = dbt.failed_tests()
    quality_results = quality.recent_results(100)

    if asset:
        needle = asset.casefold()
        quality_results = [
            item for item in quality_results
            if needle in item["asset"].casefold() or needle in item["check_id"].casefold()
        ]

    causes: list[dict[str, Any]] = []
    for name, check in health["checks"].items():
        if check["status"] == "FAIL":
            causes.append({"cause": f"PLATFORM_{name.upper()}", "confidence": 0.95, "evidence": [check["detail"]]})
    if airflow.get("parse_failures"):
        causes.append({"cause": "AIRFLOW_PARSE_FAILURE", "confidence": 0.98, "evidence": airflow["parse_failures"]})
    if failed_tests:
        causes.append({"cause": "DBT_TEST_FAILURE", "confidence": 0.9, "evidence": failed_tests})
    failing_quality = [item for item in quality_results if item["status"] == "FAIL"]
    if failing_quality:
        causes.append({"cause": "DATA_QUALITY_FAILURE", "confidence": 0.92, "evidence": failing_quality[:10]})

    causes.sort(key=lambda item: item["confidence"], reverse=True)
    return {
        "asset": asset,
        "probable_cause": causes[0] if causes else None,
        "candidate_causes": causes,
        "supporting_evidence": {
            "platform_health": health,
            "airflow": airflow,
            "dbt_failed_tests": failed_tests,
            "quality_failures": failing_quality,
        },
        "status": "DIAGNOSED" if causes else "HEALTHY_OR_INSUFFICIENT_EVIDENCE",
        "recommended_action": (
            "Inspect the highest-confidence evidence, reproduce with read-only tools, then create a proposal."
            if causes else "No deterministic failure evidence is currently present."
        ),
    }


def asset_health(project: str | Path, quality_database: str | Path, asset: str) -> dict[str, Any]:
    root = Path(project)
    graph = PlatformAssetGraph.build(root)
    lineage = graph.lineage(asset, depth=4)
    quality = SQLiteQualityStore(quality_database)
    quality.initialize()
    failures = [
        item for item in quality.recent_results(200)
        if item["status"] == "FAIL" and asset.casefold() in item["asset"].casefold()
    ]
    score = 100
    score -= min(60, len(failures) * 25)
    score -= 10 if not lineage["upstream"] and not lineage["downstream"] else 0
    return {
        "asset": lineage["asset"],
        "score": max(0, score),
        "status": "PASS" if score >= 90 else "WARN" if score >= 70 else "FAIL",
        "quality_failures": failures,
        "upstream_count": len(lineage["upstream"]),
        "downstream_count": len(lineage["downstream"]),
        "evidence": ["cross-system asset graph", "SQLite quality store"],
    }


def overall_pipeline_health(project: str | Path, quality_database: str | Path) -> dict[str, Any]:
    root = Path(project)
    airflow_health = pipeline_health(root)
    quality = SQLiteQualityStore(quality_database)
    quality.initialize()
    summary = quality.summary()
    fail_count = summary["status_counts"].get("FAIL", 0)
    quality_score = max(0, 100 - min(70, fail_count * 20))
    score = round((airflow_health["score"] * 0.45) + (quality_score * 0.55))
    return {
        "score": score,
        "status": "PASS" if score >= 90 else "WARN" if score >= 70 else "FAIL",
        "components": {
            "airflow": airflow_health,
            "quality": {"score": quality_score, "failures": fail_count, "summary": summary},
        },
    }
