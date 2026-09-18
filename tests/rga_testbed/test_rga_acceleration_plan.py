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


def test_acceleration_plan_splits_semantic_and_ai_paths(tmp_path: Path):
    module = load_module(
        "rga_acceleration_plan_test",
        ROOT / "scripts" / "rga_testbed" / "generate_acceleration_plan.py",
    )
    plan = module.build_plan("RGA_SYNTHETIC_TESTBED")
    assert plan["max_staleness_sec"] >= 120
    assert plan["semantic_view"] == "RGA_SYNTHETIC_TESTBED.SEMANTIC.RGA_REINSURANCE_PERFORMANCE"
    assert len(plan["semantic_sql"]["materializations"]) >= 3
    assert "underlying_mart_optimization" == plan["ai_physical_sql"]["strategy"]
    assert any(
        rule["candidate"] == "dynamic_table_or_aggregate_table"
        for rule in plan["ai_physical_sql"]["telemetry_rules"]
    )


def test_non_additive_ratio_is_not_marked_reaggregatable():
    module = load_module(
        "rga_acceleration_ratio_test",
        ROOT / "scripts" / "rga_testbed" / "generate_acceleration_plan.py",
    )
    plan = module.build_plan("RGA_SYNTHETIC_TESTBED")
    ratio = next(
        item
        for item in plan["semantic_sql"]["materializations"]
        if item["query_id"] == "monthly_loss_ratio_by_cedant"
    )
    assert ratio["metrics"] == ["CEDED_LOSS_RATIO"]
    assert ratio["reaggregatable"] is False
    assert ratio["coverage"] == "exact_or_more_restrictive_grain"


def test_materialization_sql_is_template_and_not_auto_deploy(tmp_path: Path):
    module = load_module(
        "rga_acceleration_sql_test",
        ROOT / "scripts" / "rga_testbed" / "generate_acceleration_plan.py",
    )
    files = module.generate(tmp_path, "RGA_SYNTHETIC_TESTBED")
    assert len(files) == 4
    sql = (tmp_path / "semantic_materializations.template.sql").read_text(encoding="utf-8")
    assert "ALTER SEMANTIC VIEW RGA_SYNTHETIC_TESTBED.SEMANTIC.RGA_REINSURANCE_PERFORMANCE SET MAX_STALENESS" in sql
    assert "ADD MATERIALIZATION" in sql
    assert "<MATERIALIZATION_WAREHOUSE>" in sql
    assert "SHOW MATERIALIZATIONS IN SEMANTIC VIEW" in sql
    sync_sql = (tmp_path / "sync_semantic_materializations.template.sql").read_text(encoding="utf-8")
    desired = (tmp_path / "semantic_materializations.yml").read_text(encoding="utf-8")
    assert "SYSTEM$MANAGE_SEMANTIC_VIEW_MATERIALIZATIONS_FROM_YAML" in sync_sql
    assert "materializations:" in desired
    assert "<MATERIALIZATION_WAREHOUSE>" in desired
