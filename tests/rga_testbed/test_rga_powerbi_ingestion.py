from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_powerbi_ingestion_readiness_accepts_supported_file(tmp_path: Path):
    module = load_module(
        "rga_powerbi_ingestion_test",
        ROOT / "scripts" / "rga_testbed" / "prepare_powerbi_ingestion.py",
    )
    source = tmp_path / "model.pbit"
    source.write_bytes(b"synthetic-test-template")
    report = module.assess(source)
    assert report["status"] == "READY_FOR_AUTOPILOT"
    assert report["sha256"]
    assert report["snowflake_handoff"]["surface"] == "Semantic View Autopilot"
    assert "supported_dax_measures" in report["snowflake_handoff"]["expected_preservation"]
    assert "run_cross_consumer_parity_suite" in report["snowflake_handoff"]["post_ingestion_required"]


def test_powerbi_ingestion_readiness_rejects_wrong_extension(tmp_path: Path):
    module = load_module(
        "rga_powerbi_ingestion_extension_test",
        ROOT / "scripts" / "rga_testbed" / "prepare_powerbi_ingestion.py",
    )
    source = tmp_path / "model.json"
    source.write_text("{}", encoding="utf-8")
    report = module.assess(source)
    assert report["status"] == "NOT_READY"
    assert any(".pbix or .pbit" in error for error in report["errors"])


def test_powerbi_ingestion_readiness_surfaces_known_limitations(tmp_path: Path):
    module = load_module(
        "rga_powerbi_ingestion_limits_test",
        ROOT / "scripts" / "rga_testbed" / "prepare_powerbi_ingestion.py",
    )
    source = tmp_path / "model.pbix"
    source.write_bytes(b"synthetic-report")
    report = module.assess(source)
    warning_text = " ".join(report["warnings"])
    assert "Report-level measures" in warning_text
    assert "Time-intelligence" in warning_text
    assert "Parameterized Snowflake connections" in warning_text
