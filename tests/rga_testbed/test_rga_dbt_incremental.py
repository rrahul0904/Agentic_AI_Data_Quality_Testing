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


def test_generated_facts_are_incremental_merge_models(tmp_path: Path):
    module = load_module(
        "rga_dbt_incremental_test",
        ROOT / "scripts" / "rga_testbed" / "generate_dbt_project.py",
    )
    module.build_project(
        module.load_config(ROOT / "config" / "rga_domain.yml"),
        tmp_path,
    )

    expected = {
        "models/core/fct_premium.sql": "premium_txn_id",
        "models/core/fct_claim.sql": "claim_id",
        "models/core/fct_exposure.sql": "exposure_id",
    }
    for relative, unique_key in expected.items():
        sql = (tmp_path / relative).read_text(encoding="utf-8")
        assert "materialized='incremental'" in sql
        assert f"unique_key='{unique_key}'" in sql
        assert "incremental_strategy='merge'" in sql
        assert "{% if is_incremental() %}" in sql
        assert "source_updated_at" in sql
        assert "from {{ this }}" in sql
        assert ">= (" in sql


def test_generated_mart_recomputes_only_affected_grains_incrementally(tmp_path: Path):
    module = load_module(
        "rga_dbt_mart_incremental_test",
        ROOT / "scripts" / "rga_testbed" / "generate_dbt_project.py",
    )
    module.build_project(
        module.load_config(ROOT / "config" / "rga_domain.yml"),
        tmp_path,
    )

    sql = (
        tmp_path / "models" / "marts" / "mart_reinsurance_performance.sql"
    ).read_text(encoding="utf-8")

    assert "materialized='incremental'" in sql
    assert "unique_key=['cedant_id', 'treaty_id', 'period_month']" in sql
    assert "incremental_strategy='merge'" in sql
    assert "affected_keys as" in sql
    assert sql.count("{% if is_incremental() %}") >= 4
    assert "where source_updated_at >= (select last_updated_at from watermark)" in sql
    assert "where c.source_updated_at >= (select last_updated_at from watermark)" in sql
    assert "join {{ ref('fct_premium') }} p" in sql
    assert "join {{ ref('fct_claim') }} c" in sql
    assert "join {{ ref('fct_exposure') }} e" in sql
    assert "greatest_ignore_nulls(" in sql
    assert "as source_updated_at" in sql


def test_generated_mart_has_explicit_composite_grain_uniqueness_test(tmp_path: Path):
    module = load_module(
        "rga_dbt_grain_test",
        ROOT / "scripts" / "rga_testbed" / "generate_dbt_project.py",
    )
    module.build_project(
        module.load_config(ROOT / "config" / "rga_domain.yml"),
        tmp_path,
    )

    test_sql = (
        tmp_path / "tests" / "mart_reinsurance_performance_grain_unique.sql"
    ).read_text(encoding="utf-8")
    assert "cedant_id" in test_sql
    assert "treaty_id" in test_sql
    assert "period_month" in test_sql
    assert "having count(*) > 1" in test_sql


def test_dimension_models_remain_full_rebuild_for_correction_safety(tmp_path: Path):
    module = load_module(
        "rga_dbt_dimension_safety_test",
        ROOT / "scripts" / "rga_testbed" / "generate_dbt_project.py",
    )
    module.build_project(
        module.load_config(ROOT / "config" / "rga_domain.yml"),
        tmp_path,
    )

    policy = (tmp_path / "models" / "core" / "dim_policy.sql").read_text(
        encoding="utf-8"
    )
    assert "materialized='incremental'" not in policy
    assert "{{ config(alias='DIM_POLICY') }}" in policy
