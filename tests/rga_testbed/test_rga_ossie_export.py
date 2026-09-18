from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_ossie_export_preserves_governed_metrics_and_grain(tmp_path: Path):
    module = load_module("rga_ossie_test", ROOT / "scripts" / "rga_testbed" / "export_ossie.py")
    model = module.build_ossie_model("RGA_SYNTHETIC_TESTBED")
    assert model["version"] == "0.2.0.dev0"
    dataset = model["datasets"][0]
    assert dataset["source"] == "RGA_SYNTHETIC_TESTBED.MART.REINSURANCE_PERFORMANCE"
    assert dataset["primary_key"] == ["cedant_id", "treaty_id", "period_month"]
    metrics = {item["name"]: item for item in model["metrics"]}
    assert "ceded_loss_ratio" in metrics
    expression = metrics["ceded_loss_ratio"]["expression"]["dialects"][0]
    assert expression["dialect"] == "SNOWFLAKE"
    assert "reinsurance_performance.ceded_claim_amount" in expression["expression"].lower()


def test_ossie_export_preserves_snowflake_only_capabilities_as_extension(tmp_path: Path):
    module = load_module("rga_ossie_ext_test", ROOT / "scripts" / "rga_testbed" / "export_ossie.py")
    output = tmp_path / "model.ossie.yml"
    module.generate(output, "RGA_SYNTHETIC_TESTBED")
    model = yaml.safe_load(output.read_text(encoding="utf-8"))
    ext = model["custom_extensions"][0]
    assert ext["vendor"] == "snowflake"
    assert ext["name"] == "governed_semantic_runtime"
    assert len(ext["value"]["verified_queries"]) >= 3
    assert ext["value"]["consumers"]["ai"]["allow_unrestricted_sql"] is False
    assert "semantic_sql" in ext["value"]["acceleration"]
