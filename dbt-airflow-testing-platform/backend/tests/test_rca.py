import json

from app.models import DbtProject
from app.models_quality import Certification, Evidence, QualityRule, QualityRuleRun
from app.services.rca import get_upstream_chain, locate_root_cause

LINEAGE = {
    "nodes": [
        {"id": "seed.p.raw_orders", "label": "raw_orders", "kind": "seed"},
        {"id": "model.p.stg_orders", "label": "stg_orders", "kind": "model"},
        {"id": "model.p.int_revenue", "label": "int_revenue", "kind": "model"},
        {"id": "model.p.fact_revenue", "label": "fact_revenue", "kind": "model"},
    ],
    "edges": [
        {"from": "seed.p.raw_orders", "to": "model.p.stg_orders"},
        {"from": "model.p.stg_orders", "to": "model.p.int_revenue"},
        {"from": "model.p.int_revenue", "to": "model.p.fact_revenue"},
    ],
}


def test_get_upstream_chain_orders_upstream_first():
    chain = get_upstream_chain(LINEAGE, "fact_revenue")
    assert chain == ["stg_orders", "int_revenue", "fact_revenue"]


def test_get_upstream_chain_unknown_target_returns_itself():
    assert get_upstream_chain(LINEAGE, "not_in_lineage") == ["not_in_lineage"]


def _make_project(db, lineage=LINEAGE) -> DbtProject:
    project = DbtProject(
        name="test project", execution_mode="local", adapter="duckdb",
        venv_path="/tmp/venv", project_dir="/tmp/project", profiles_dir="/tmp/project/profiles",
        lineage_json=json.dumps(lineage), status="READY",
    )
    db.add(project)
    db.commit()
    return project


def _make_failing_rule_with_evidence(db, project, *, target_table: str, rule_name: str) -> None:
    rule = QualityRule(
        dbt_project_id=project.id, name=rule_name, dimension="accuracy", rule_type="custom_sql",
        target_table=target_table, severity="P1",
    )
    db.add(rule)
    db.flush()
    run = QualityRuleRun(quality_rule_id=rule.id, status="FAIL", measured_value=3.0)
    db.add(run)
    db.flush()
    db.add(
        Evidence(
            quality_rule_run_id=run.id, evidence_type="QUERY_RESULT", source_type="duckdb",
            dataset_ref=target_table, value="3.0",
        )
    )
    db.add(
        Certification(
            dataset_ref=target_table, dbt_project_id=project.id, status="FAILED",
            reason=f"P1 rule(s) failing: {rule_name}.",
        )
    )
    db.commit()


def test_locate_root_cause_finds_upstream_failure_and_links_evidence(db_session):
    project = _make_project(db_session)
    _make_failing_rule_with_evidence(db_session, project, target_table="int_revenue", rule_name="row coverage")

    claim = locate_root_cause(db_session, project, "fact_revenue")

    assert claim.status == "SUPPORTED"
    assert "int_revenue" in claim.statement
    assert len(claim.evidence_links) == 1


def test_locate_root_cause_unverified_when_nothing_upstream_is_failing(db_session):
    project = _make_project(db_session)
    claim = locate_root_cause(db_session, project, "fact_revenue")
    assert claim.status == "UNVERIFIED"
    assert claim.evidence_links == []


def test_locate_root_cause_scopes_by_project(db_session):
    """Regression test for a real bug: certifications/rules from a
    different dbt project sharing a table name (e.g. two projects both
    having "int_revenue") must not be picked up as the root cause."""
    project_a = _make_project(db_session)
    project_b = DbtProject(
        name="other project", execution_mode="local", adapter="duckdb",
        venv_path="/tmp/venv2", project_dir="/tmp/project2", profiles_dir="/tmp/project2/profiles",
        lineage_json=json.dumps(LINEAGE), status="READY",
    )
    db_session.add(project_b)
    db_session.commit()

    # Only project_b's int_revenue is failing -- project_a's is clean.
    _make_failing_rule_with_evidence(db_session, project_b, target_table="int_revenue", rule_name="row coverage")

    claim = locate_root_cause(db_session, project_a, "fact_revenue")
    assert claim.status == "UNVERIFIED"  # project_a has no failing upstream certification of its own
