from __future__ import annotations

from agentic_data_platform.skills import BUILTIN_SKILLS, SkillService


ALTIMATE_EXPECTED = {
    "altimate-setup",
    "cost-report",
    "data-parity",
    "data-viz",
    "dbt-analyze",
    "dbt-develop",
    "dbt-docs",
    "dbt-pr-review",
    "dbt-schema-verify",
    "dbt-test",
    "dbt-troubleshoot",
    "dbt-unit-tests",
    "lineage-diff",
    "pii-audit",
    "query-optimize",
    "schema-migration",
    "sql-review",
    "sql-translate",
    "teach",
    "train",
    "training-status",
}

AIRFLOW_EXPECTED = {
    "airflow-analyze", "airflow-troubleshoot", "airflow-backfill", "airflow-optimize",
    "airflow-upgrade", "airflow-assets", "airflow-capacity", "airflow-cost",
    "airflow-security", "pipeline-health", "root-cause",
}
EXPECTED = ALTIMATE_EXPECTED | AIRFLOW_EXPECTED


def test_builtin_skill_catalog_preserves_reference_and_adds_airflow_superset():
    assert set(BUILTIN_SKILLS) == EXPECTED
    assert len(ALTIMATE_EXPECTED) == 21
    assert len(BUILTIN_SKILLS) == 32


def test_install_all_enable_disable_and_plan(tmp_path):
    service = SkillService(tmp_path, state_path=tmp_path / ".ade" / "skills.db")
    installed = service.install_all()
    assert installed["count"] == 32
    assert {item["name"] for item in service.list()} == EXPECTED

    disabled = service.set_enabled("sql-review", False)
    assert disabled["enabled"] is False
    assert service.plan("sql-review", {"sql_review", "sql_column_lineage", "pii_policy_check"})["status"] == "DISABLED"

    service.set_enabled("sql-review", True)
    ready = service.plan(
        "sql-review",
        {"sql_review", "sql_column_lineage", "pii_policy_check"},
    )
    assert ready["status"] == "READY"
    assert [item["tool"] for item in ready["steps"]] == [
        "sql_review",
        "sql_column_lineage",
        "pii_policy_check",
    ]


def test_skill_execute_preserves_order_and_stops_on_failure(tmp_path):
    service = SkillService(tmp_path, state_path=tmp_path / "skills.db")
    service.install("sql-review")
    calls = []

    def invoke(name, args):
        calls.append(name)
        if name == "sql_column_lineage":
            return {"status": "FAIL", "reason": "fixture"}
        return {"status": "PASS"}

    result = service.execute(
        "sql-review",
        available_tools={"sql_review", "sql_column_lineage", "pii_policy_check"},
        invoke=invoke,
        args={"sql": "SELECT 1"},
    )
    assert result["status"] == "FAIL"
    assert calls == ["sql_review", "sql_column_lineage"]


def test_skill_missing_tools_blocks_before_execution(tmp_path):
    service = SkillService(tmp_path, state_path=tmp_path / "skills.db")
    service.install("pii-audit")
    plan = service.plan("pii-audit", {"pii_scan"})
    assert plan["status"] == "BLOCKED"
    assert {"pii_lineage", "pii_access_report"} == set(plan["missing_tools"])
