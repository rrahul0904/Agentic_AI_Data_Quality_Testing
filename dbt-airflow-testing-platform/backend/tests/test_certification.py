from app.models_quality import QualityRule, QualityRuleRun
from app.services.certification import evaluate_certification


def _add_rule_with_run(db, *, dataset_ref: str, severity: str, status: str) -> None:
    rule = QualityRule(
        name=f"{dataset_ref}-{severity}-{status}", dimension="completeness", rule_type="not_null",
        target_table=dataset_ref, target_column="id", severity=severity,
    )
    db.add(rule)
    db.flush()
    db.add(QualityRuleRun(quality_rule_id=rule.id, status=status, measured_value=0.0))
    db.commit()


def test_no_rules_yields_unknown(db_session):
    cert = evaluate_certification(db_session, "nonexistent_table")
    assert cert.status == "UNKNOWN"


def test_all_pass_yields_certified(db_session):
    _add_rule_with_run(db_session, dataset_ref="fct_orders", severity="P1", status="PASS")
    _add_rule_with_run(db_session, dataset_ref="fct_orders", severity="P2", status="PASS")
    cert = evaluate_certification(db_session, "fct_orders")
    assert cert.status == "CERTIFIED"


def test_p1_failure_yields_failed(db_session):
    _add_rule_with_run(db_session, dataset_ref="fct_orders", severity="P1", status="FAIL")
    _add_rule_with_run(db_session, dataset_ref="fct_orders", severity="P2", status="PASS")
    cert = evaluate_certification(db_session, "fct_orders")
    assert cert.status == "FAILED"
    assert "P1" in cert.reason


def test_only_p2_failure_yields_at_risk(db_session):
    _add_rule_with_run(db_session, dataset_ref="fct_orders", severity="P1", status="PASS")
    _add_rule_with_run(db_session, dataset_ref="fct_orders", severity="P2", status="FAIL")
    cert = evaluate_certification(db_session, "fct_orders")
    assert cert.status == "AT_RISK"


def test_p1_error_also_yields_failed(db_session):
    _add_rule_with_run(db_session, dataset_ref="fct_orders", severity="P1", status="ERROR")
    cert = evaluate_certification(db_session, "fct_orders")
    assert cert.status == "FAILED"


def test_scoped_by_project_when_table_names_collide(db_session):
    """Regression test for a real bug: two dbt projects with a model of the
    same name must not have their rules conflated when dbt_project_id is
    supplied."""
    rule_a = QualityRule(
        dbt_project_id="project-a", name="a-rule", dimension="completeness", rule_type="not_null",
        target_table="int_revenue", target_column="id", severity="P1",
    )
    rule_b = QualityRule(
        dbt_project_id="project-b", name="b-rule", dimension="completeness", rule_type="not_null",
        target_table="int_revenue", target_column="id", severity="P1",
    )
    db_session.add_all([rule_a, rule_b])
    db_session.flush()
    db_session.add(QualityRuleRun(quality_rule_id=rule_a.id, status="PASS"))
    db_session.add(QualityRuleRun(quality_rule_id=rule_b.id, status="FAIL"))
    db_session.commit()

    cert_a = evaluate_certification(db_session, "int_revenue", dbt_project_id="project-a")
    cert_b = evaluate_certification(db_session, "int_revenue", dbt_project_id="project-b")

    assert cert_a.status == "CERTIFIED"
    assert cert_b.status == "FAILED"


def test_disabled_rule_excluded(db_session):
    rule = QualityRule(
        name="disabled rule", dimension="completeness", rule_type="not_null",
        target_table="fct_orders", target_column="id", severity="P1", status="DISABLED",
    )
    db_session.add(rule)
    db_session.commit()
    cert = evaluate_certification(db_session, "fct_orders")
    assert cert.status == "UNKNOWN"
