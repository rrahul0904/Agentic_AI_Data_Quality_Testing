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


def test_multi_fact_plan_requires_safe_shared_grain():
    module = load_module(
        "rga_multi_fact_plan_test",
        ROOT / "scripts" / "rga_testbed" / "generate_multi_fact_certification.py",
    )
    plan = module.build_plan()
    assert plan["shared_grain"] == ["CEDANT_ID", "TREATY_ID", "PERIOD_MONTH"]
    assert len(plan["facts"]) == 3
    assert "aggregate_each_fact_to_shared_grain_before_join" in plan["planning_rules"]
    assert "never_join_raw_fact_tables_directly" in plan["planning_rules"]
    assert "CEDED_LOSS_RATIO" in plan["derived_metrics"]


def test_multi_fact_reference_aggregates_before_join(tmp_path: Path):
    module = load_module(
        "rga_multi_fact_sql_test",
        ROOT / "scripts" / "rga_testbed" / "generate_multi_fact_certification.py",
    )
    module.generate(tmp_path)
    sql = (tmp_path / "multi_fact_reference.sql").read_text(encoding="utf-8").lower()
    assert "premium_monthly as" in sql
    assert "claim_monthly as" in sql
    assert "exposure_monthly as" in sql
    assert "keys as" in sql
    assert sql.count("group by 1, 2, 3") == 3
    assert "left join premium_monthly" in sql
    assert "left join claim_monthly" in sql
    assert "left join exposure_monthly" in sql
    assert "fct_premium p join" not in sql
    assert "fct_claim c join rga_synthetic_testbed.core.fct_exposure" not in sql
