from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_rga_contract_has_enterprise_relationships():
    config = yaml.safe_load((ROOT / "config" / "rga_domain.yml").read_text(encoding="utf-8"))
    entities = config["entities"]
    assert config["domain"] == "rga_life_health_reinsurance"
    assert len(entities) >= 12
    assert entities["policies"]["foreign_keys"]["treaty_id"] == "treaties.treaty_id"
    assert entities["claims"]["foreign_keys"]["policy_id"] == "policies.policy_id"
    assert entities["exposure_monthly"]["foreign_keys"]["cedant_id"] == "cedants.cedant_id"
    assert config["presets"]["stress"]["policies"] >= 100_000_000


def test_tiny_generation_is_relational_and_valid(tmp_path: Path):
    generator = load_module("rga_generate", ROOT / "scripts" / "rga_testbed" / "generate_data.py")
    validator = load_module("rga_validate", ROOT / "scripts" / "rga_testbed" / "validate_dataset.py")
    config = generator.load_config(ROOT / "config" / "rga_domain.yml")
    output = tmp_path / "rga"
    manifest = generator.build_dataset(config, "tiny", 42, date(2026, 9, 1), output, policy_override=120)
    assert manifest["synthetic_only"] is True
    assert manifest["counts"]["policies"] == 120
    assert manifest["counts"]["insured_lives"] == 120
    assert manifest["counts"]["claims"] > 0
    assert manifest["counts"]["exposure_monthly"] > manifest["counts"]["policies"]
    result = validator.validate(output)
    assert result["status"] == "PASS", result["errors"]


def test_generation_is_deterministic(tmp_path: Path):
    generator = load_module("rga_generate_repeat", ROOT / "scripts" / "rga_testbed" / "generate_data.py")
    config = generator.load_config(ROOT / "config" / "rga_domain.yml")
    left = generator.build_dataset(config, "tiny", 7, date(2026, 9, 1), tmp_path / "left", policy_override=50)
    right = generator.build_dataset(config, "tiny", 7, date(2026, 9, 1), tmp_path / "right", policy_override=50)
    assert left["generation_id"] == right["generation_id"]
    assert [item["checksum"] for item in left["files"]] == [item["checksum"] for item in right["files"]]


def test_snowflake_ddl_contains_all_raw_tables():
    ddl_module = load_module("rga_ddl", ROOT / "scripts" / "rga_testbed" / "generate_snowflake_ddl.py")
    config = ddl_module.load_config(ROOT / "config" / "rga_domain.yml")
    ddl = ddl_module.compile_ddl(config, "RGA_SYNTHETIC_TESTBED")
    assert "CREATE DATABASE IF NOT EXISTS RGA_SYNTHETIC_TESTBED" in ddl
    assert "CREATE TABLE IF NOT EXISTS RAW.POLICIES" in ddl
    assert "CREATE TABLE IF NOT EXISTS RAW.CLAIMS" in ddl
    assert "CREATE TABLE IF NOT EXISTS RAW.EXPOSURE_MONTHLY" in ddl
    assert "AUDIT.SYNTHETIC_GENERATION_MANIFEST" in ddl
    assert "Synthetic RGA-like test data only" in ddl
