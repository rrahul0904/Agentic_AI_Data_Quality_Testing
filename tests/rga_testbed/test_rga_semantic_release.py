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


def test_interchange_report_is_explicit_about_round_trip_boundary():
    module = load_module(
        "rga_interchange_compat_test",
        ROOT / "scripts" / "rga_testbed" / "report_interchange_compatibility.py",
    )
    report = module.build_report("RGA_SYNTHETIC_TESTBED")
    assert report["status"] == "SUPPORTED_WITH_EXTENSIONS"
    assert report["round_trip_import_supported"] is False
    assert report["not_exported"] == []
    assert "verified_queries" in report["preserved_as_custom_extensions"]
    assert report["source_metric_count"] >= 8


def test_release_bundle_contains_all_governed_surfaces(tmp_path: Path):
    module = load_module(
        "rga_release_bundle_test",
        ROOT / "scripts" / "rga_testbed" / "build_semantic_release.py",
    )
    release = module.build_release(
        tmp_path / "release",
        "RGA_SYNTHETIC_TESTBED",
        source_sha="test-sha",
    )
    root = tmp_path / "release"
    assert release["source_sha"] == "test-sha"
    assert release["generated_file_count"] >= 18
    assert (root / "manifest" / "semantic_manifest.json").exists()
    assert (root / "semantic" / "rga_reinsurance_performance.yml").exists()
    assert (root / "ai" / "create_agent.sql").exists()
    assert (root / "microsoft" / "consumer_contract.json").exists()
    assert (root / "benchmarks" / "manifest.json").exists()
    assert (root / "parity" / "parity_manifest.json").exists()
    assert (root / "acceleration" / "semantic_materializations.yml").exists()
    assert (root / "interchange" / "rga_reinsurance_performance.ossie.yml").exists()
    assert "power_bi_excel_governed_parity" in release["external_certification_required"]

    persisted = json.loads((root / "release_manifest.json").read_text(encoding="utf-8"))
    assert persisted["semantic_manifest_sha256"] == release["semantic_manifest_sha256"]
    assert all(item["sha256"] for item in persisted["files"])


def test_release_bundle_uses_manifest_diff_for_impacted_artifacts(tmp_path: Path):
    manifest_module = load_module(
        "rga_release_manifest_baseline_test",
        ROOT / "scripts" / "rga_testbed" / "compile_semantic_manifest.py",
    )
    release_module = load_module(
        "rga_release_diff_test",
        ROOT / "scripts" / "rga_testbed" / "build_semantic_release.py",
    )
    baseline = manifest_module.build_manifest()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    release = release_module.build_release(
        tmp_path / "release",
        "RGA_SYNTHETIC_TESTBED",
        baseline_path=baseline_path,
    )
    assert release["change_status"] == "UNCHANGED"
    assert release["change_risk"]["risk"] == "none"
    assert release["change_risk"]["approval_required"] is False
    assert release["impacted_artifacts"] == []
    diff = json.loads((tmp_path / "release" / "manifest" / "semantic_diff.json").read_text(encoding="utf-8"))
    assert diff["status"] == "UNCHANGED"
    risk = json.loads((tmp_path / "release" / "manifest" / "semantic_change_risk.json").read_text(encoding="utf-8"))
    assert risk["risk"] == "none"
