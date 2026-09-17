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


def test_load_sql_covers_all_rga_entities():
    module = load_module("rga_load_sql", ROOT / "scripts" / "rga_testbed" / "generate_load_sql.py")
    config = module.load_config(ROOT / "config" / "rga_domain.yml")
    sql = module.compile_load_sql(config, "RGA_SYNTHETIC_TESTBED", "artifacts/rga_testbed/csv")
    assert sql.count("COPY INTO RAW.") == len(config["entities"])
    assert "COPY INTO RAW.POLICIES" in sql
    assert "COPY INTO RAW.CLAIMS" in sql
    assert "COPY INTO RAW.EXPOSURE_MONTHLY" in sql
    assert "METADATA$FILENAME" in sql
    assert "ON_ERROR='ABORT_STATEMENT'" in sql


def test_dbt_project_generates_staging_core_and_mart(tmp_path: Path):
    module = load_module("rga_dbt", ROOT / "scripts" / "rga_testbed" / "generate_dbt_project.py")
    config = module.load_config(ROOT / "config" / "rga_domain.yml")
    output = tmp_path / "dbt"
    files = module.build_project(config, output)
    assert len(list((output / "models" / "staging").glob("stg_*.sql"))) == len(config["entities"])
    assert (output / "models" / "core" / "dim_policy.sql").exists()
    assert (output / "models" / "core" / "fct_claim.sql").exists()
    mart = (output / "models" / "marts" / "mart_reinsurance_performance.sql").read_text(encoding="utf-8")
    assert "REINSURANCE_PERFORMANCE" in mart
    assert "ceded_loss_ratio" in mart
    assert "union" in mart.lower()
    assert any(path.name == "sources.yml" for path in files)


def test_semantic_view_has_governed_business_metrics(tmp_path: Path):
    module = load_module("rga_semantic", ROOT / "scripts" / "rga_testbed" / "generate_semantic_view.py")
    spec = module.build_semantic_spec("RGA_SYNTHETIC_TESTBED")
    table = spec["tables"][0]
    metric_names = {metric["name"] for metric in table["metrics"]}
    assert table["base_table"] == {
        "database": "RGA_SYNTHETIC_TESTBED",
        "schema": "MART",
        "table": "REINSURANCE_PERFORMANCE",
    }
    assert {"TOTAL_GROSS_PREMIUM", "TOTAL_CEDED_PREMIUM", "TOTAL_CEDED_CLAIMS", "CEDED_LOSS_RATIO"} <= metric_names
    files = module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    semantic_yaml = yaml.safe_load((tmp_path / "rga_reinsurance_performance.yml").read_text(encoding="utf-8"))
    assert semantic_yaml["name"] == "RGA_REINSURANCE_PERFORMANCE"
    assert len(files) == 3


def test_semantic_verify_and_deploy_are_separate(tmp_path: Path):
    module = load_module("rga_semantic_sql", ROOT / "scripts" / "rga_testbed" / "generate_semantic_view.py")
    module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    verify_sql = (tmp_path / "verify_semantic_view.sql").read_text(encoding="utf-8")
    deploy_sql = (tmp_path / "deploy_semantic_view.sql").read_text(encoding="utf-8")
    assert "SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML" in verify_sql
    assert "RGA_SYNTHETIC_TESTBED.SEMANTIC" in verify_sql
    assert "  TRUE,\n  TRUE" in verify_sql
    assert "  FALSE,\n  TRUE" in deploy_sql
