from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _module():
    return load_module(
        "rga_certification_report_test",
        ROOT / "scripts" / "rga_testbed" / "build_certification_report.py",
    )


def _write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _parity_manifest():
    return {
        "required_consumers": [
            "snowflake_semantic_view",
            "cortex_agent_mcp",
            "power_bi",
            "excel",
        ],
        "cases": [{"id": "q1"}],
    }


def test_certification_report_is_truthful_when_only_repository_release_exists(tmp_path: Path):
    module = _module()
    workspace = tmp_path / "demo"
    evidence_dir = workspace / "external-evidence"

    _write(
        workspace / "release" / "release_manifest.json",
        {
            "source_sha": "abc123",
            "semantic_manifest_sha256": "semantic-hash",
            "generated_file_count": 20,
            "change_status": "FULL_BUILD",
        },
    )
    _write(
        workspace / "release" / "parity" / "parity_manifest.json",
        _parity_manifest(),
    )

    report = module.build_report(workspace, evidence_dir)
    assert report["overall_status"] == "REPOSITORY_READY_LIVE_CERTIFICATION_PENDING"
    assert report["end_to_end_certified"] is False
    assert report["production_rollout_certified"] is False
    assert report["release"]["status"] == "PASS"
    assert report["live_runtime"]["status"] == "PENDING"
    assert report["consumer_parity"]["status"] == "PENDING"
    assert report["change_data"]["status"] == "PENDING"
    assert report["scale_validation"]["status"] == "PENDING"
    assert report["consumer_parity"]["evidence"]["expected"] == 4
    assert report["consumer_parity"]["evidence"]["captured"] == 0
    assert any("live Snowflake" in blocker for blocker in report["blockers"])
    assert any("0/4 captured" in blocker for blocker in report["blockers"])

    markdown = module.render_markdown(report)
    assert "End-to-end certified for executed workload:** NO" in markdown
    assert "Production rollout certified:** NO" in markdown
    assert "REPOSITORY_READY_LIVE_CERTIFICATION_PENDING" in markdown


def test_certification_report_marks_production_only_after_all_surfaces_pass(tmp_path: Path):
    module = _module()
    workspace = tmp_path / "demo"
    evidence_dir = workspace / "external-evidence"

    _write(
        workspace / "release" / "release_manifest.json",
        {
            "source_sha": "abc123",
            "semantic_manifest_sha256": "semantic-hash",
            "generated_file_count": 20,
            "change_status": "UNCHANGED",
        },
    )
    _write(
        workspace / "release" / "parity" / "parity_manifest.json",
        _parity_manifest(),
    )
    _write(
        workspace / "evidence" / "certification_manifest.json",
        {
            "status": "PASS",
            "acceptance": {
                "deployment_pass": True,
                "all_benchmarks_pass": True,
                "all_direct_semantic_result_parity_pass": True,
            },
            "environment": {"account": "acct", "warehouse": "wh", "role": "ROLE_ANALYST"},
        },
    )
    _write(
        workspace / "evidence" / "agent_smoke.json",
        {"status": "PASS", "passed": 1, "failed": 0},
    )
    _write(
        workspace / "evidence" / "cross_consumer_parity.json",
        {"status": "PASS", "failed_cases": 0},
    )
    _write(
        workspace / "evidence" / "workload_analysis.json",
        {"status": "ANALYZED", "recommendations": [{"candidate": "materialization"}]},
    )
    _write(
        workspace / "evidence" / "cdc_application.json",
        {
            "status": "PASS",
            "verify_idempotency": True,
            "source_event_count": 15,
        },
    )
    _write(
        workspace / "evidence" / "scale_test.json",
        {
            "status": "PASS",
            "policies": 10000,
            "generation": {
                "total_rows": 125000,
                "peak_rss_mb": 72.5,
            },
            "validation": {"engine": "duckdb_out_of_core"},
            "parquet": {"status": "PASS"},
            "truth_boundary": "Executed 10k policy local scale only.",
        },
    )

    for consumer in _parity_manifest()["required_consumers"]:
        _write(
            evidence_dir / f"q1.{consumer}.json",
            {
                "case_id": "q1",
                "consumer": consumer,
                "security_context": "ROLE_ANALYST",
                "capture_status": "CAPTURED",
                "rows": [{"METRIC_A": 10}],
            },
        )

    report = module.build_report(workspace, evidence_dir)
    assert report["overall_status"] == "END_TO_END_CERTIFIED_FOR_EXECUTED_WORKLOAD"
    assert report["end_to_end_certified"] is True
    assert report["production_rollout_certified"] is False
    assert report["blockers"] == []
    assert report["production_rollout_blockers"]
    assert report["consumer_parity"]["evidence"]["captured"] == 4
    assert report["consumer_parity"]["evidence"]["status"] == "COMPLETE"
    assert report["workload_analysis"]["recommendation_count"] == 1
    assert report["change_data"]["status"] == "PASS"
    assert report["change_data"]["verify_idempotency"] is True
    assert report["change_data"]["source_event_count"] == 15
    assert report["scale_validation"]["status"] == "PASS"
    assert report["scale_validation"]["policies"] == 10000
    assert report["scale_validation"]["total_rows"] == 125000
    assert report["scale_validation"]["peak_rss_mb"] == 72.5
    assert report["scale_validation"]["validation_engine"] == "duckdb_out_of_core"
    assert report["scale_validation"]["parquet_status"] == "PASS"
    assert report["optimization"]["requested"] is False
    assert report["optimization"]["status"] == "NOT_REQUESTED"

    generated = module.generate(
        workspace,
        evidence_dir=evidence_dir,
        output_dir=workspace / "final-report",
    )
    assert generated["status"] == "PASS"
    assert generated["end_to_end_certified"] is True
    assert generated["production_rollout_certified"] is False
    assert Path(generated["json"]).exists()
    assert Path(generated["markdown"]).exists()


def test_certification_report_does_not_count_pending_files_as_captured(tmp_path: Path):
    module = _module()
    workspace = tmp_path / "demo"
    evidence_dir = workspace / "external-evidence"

    _write(workspace / "release" / "release_manifest.json", {"source_sha": "abc"})
    _write(workspace / "release" / "parity" / "parity_manifest.json", _parity_manifest())
    for consumer in _parity_manifest()["required_consumers"]:
        _write(
            evidence_dir / f"q1.{consumer}.json",
            {
                "capture_status": "PENDING",
                "rows": [],
            },
        )

    report = module.build_report(workspace, evidence_dir)
    evidence = report["consumer_parity"]["evidence"]
    assert evidence["captured"] == 0
    assert evidence["pending"] == 4
    assert report["end_to_end_certified"] is False
    assert report["production_rollout_certified"] is False


def test_certification_report_blocks_when_existing_cdc_evidence_failed(tmp_path: Path):
    module = _module()
    workspace = tmp_path / "demo"
    evidence_dir = workspace / "external-evidence"

    _write(workspace / "release" / "release_manifest.json", {"source_sha": "abc"})
    _write(workspace / "release" / "parity" / "parity_manifest.json", _parity_manifest())
    _write(
        workspace / "evidence" / "cdc_application.json",
        {"status": "FAIL", "verify_idempotency": True, "source_event_count": 15},
    )

    report = module.build_report(workspace, evidence_dir)
    assert report["change_data"]["status"] == "FAIL"
    assert any("CDC correction/late-arrival" in blocker for blocker in report["blockers"])


def test_certification_report_blocks_when_existing_scale_evidence_failed(tmp_path: Path):
    module = _module()
    workspace = tmp_path / "demo"
    evidence_dir = workspace / "external-evidence"

    _write(workspace / "release" / "release_manifest.json", {"source_sha": "abc"})
    _write(workspace / "release" / "parity" / "parity_manifest.json", _parity_manifest())
    _write(
        workspace / "evidence" / "scale_test.json",
        {
            "status": "FAIL",
            "policies": 10000,
            "generation": {"total_rows": 100000, "peak_rss_mb": 600},
            "validation": {"engine": "duckdb_out_of_core"},
            "parquet": {"status": "PASS"},
            "truth_boundary": "Executed local scale only.",
        },
    )

    report = module.build_report(workspace, evidence_dir)
    assert report["scale_validation"]["status"] == "FAIL"
    assert any("scale evidence" in blocker for blocker in report["blockers"])


def test_certification_report_surfaces_passing_requested_optimization(tmp_path: Path):
    module = _module()
    workspace = tmp_path / "demo"
    evidence_dir = workspace / "external-evidence"

    _write(workspace / "release" / "release_manifest.json", {"source_sha": "abc"})
    _write(
        workspace / "release" / "parity" / "parity_manifest.json",
        _parity_manifest(),
    )
    _write(
        workspace / "evidence" / "certification_manifest.json",
        {
            "status": "PASS",
            "acceptance": {
                "optimization_analysis_pass": True,
                "optimization_diagnostics_pass": True,
            },
            "optimization": {
                "requested": True,
                "diagnostics_requested": True,
                "status": "PASS",
                "diagnostics_status": "PASS",
                "recommendation_count": 2,
                "history_experiment_count": 3,
                "experiment_count": 5,
                "executable_physical_mutations": 0,
                "truth_boundary": "No physical mutations were applied.",
            },
        },
    )
    _write(
        workspace / "evidence" / "optimization_analysis_summary.json",
        {
            "status": "PASS",
            "recommendation_count": 2,
            "history_experiment_count": 3,
            "experiment_count": 5,
            "executable_physical_mutations": 0,
            "truth_boundary": "No physical mutations were applied.",
        },
    )
    _write(
        workspace / "evidence" / "optimization_diagnostics.json",
        {"status": "PASS", "statement_count": 4},
    )

    report = module.build_report(workspace, evidence_dir)
    assert report["optimization"]["requested"] is True
    assert report["optimization"]["diagnostics_requested"] is True
    assert report["optimization"]["status"] == "PASS"
    assert report["optimization"]["diagnostics_status"] == "PASS"
    assert report["optimization"]["recommendation_count"] == 2
    assert report["optimization"]["history_experiment_count"] == 3
    assert report["optimization"]["experiment_count"] == 5
    assert report["optimization"]["executable_physical_mutations"] == 0
    assert not any("physical-optimization analysis" in item for item in report["blockers"])
    assert not any("optimization diagnostics" in item for item in report["blockers"])


def test_certification_report_blocks_failed_requested_optimization(tmp_path: Path):
    module = _module()
    workspace = tmp_path / "demo"
    evidence_dir = workspace / "external-evidence"

    _write(workspace / "release" / "release_manifest.json", {"source_sha": "abc"})
    _write(
        workspace / "release" / "parity" / "parity_manifest.json",
        _parity_manifest(),
    )
    _write(
        workspace / "evidence" / "certification_manifest.json",
        {
            "status": "INCOMPLETE",
            "acceptance": {
                "optimization_analysis_pass": False,
                "optimization_diagnostics_pass": False,
            },
            "optimization": {
                "requested": True,
                "diagnostics_requested": True,
                "status": "FAIL",
                "diagnostics_status": "FAIL",
                "executable_physical_mutations": 0,
            },
        },
    )

    report = module.build_report(workspace, evidence_dir)
    assert report["optimization"]["requested"] is True
    assert any(
        "physical-optimization analysis has not passed" in item
        for item in report["blockers"]
    )
    assert any(
        "optimization diagnostics have not passed" in item
        for item in report["blockers"]
    )


def test_certification_report_blocks_executable_optimization_mutation(tmp_path: Path):
    module = _module()
    workspace = tmp_path / "demo"
    evidence_dir = workspace / "external-evidence"

    _write(workspace / "release" / "release_manifest.json", {"source_sha": "abc"})
    _write(
        workspace / "release" / "parity" / "parity_manifest.json",
        _parity_manifest(),
    )
    _write(
        workspace / "evidence" / "certification_manifest.json",
        {
            "status": "PASS",
            "acceptance": {
                "optimization_analysis_pass": True,
            },
            "optimization": {
                "requested": True,
                "diagnostics_requested": False,
                "status": "PASS",
                "executable_physical_mutations": 1,
            },
        },
    )
    _write(
        workspace / "evidence" / "optimization_analysis_summary.json",
        {
            "status": "PASS",
            "executable_physical_mutations": 1,
        },
    )

    report = module.build_report(workspace, evidence_dir)
    assert any(
        "zero executable physical-mutation invariant" in item
        for item in report["blockers"]
    )
