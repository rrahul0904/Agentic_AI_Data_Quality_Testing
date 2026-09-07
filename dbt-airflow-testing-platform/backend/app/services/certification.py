"""Certification status is derived from rule results -- never an arbitrary
AI-generated score (Master Prompt §35 / Architecture spec §38)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models_quality import Certification, QualityRule, QualityRuleRun


def evaluate_certification(
    db: Session, dataset_ref: str, contract_id: str | None = None, dbt_project_id: str | None = None
) -> Certification:
    """`dataset_ref` is just a table name (e.g. "int_revenue"), which is
    **not** globally unique -- two different dbt projects can both have a
    model with that name. Always pass `dbt_project_id` when the caller
    knows it (every real UI/API flow does); omitting it falls back to a
    name-only match across *all* projects, which is only safe if you know
    table names are unique in your deployment. This was a real bug found
    while running scripts/run_revenue_demo.py against a second, separate
    project: certification silently conflated rules from two unrelated
    projects that both had an "int_revenue" model."""

    def _make(status: str, reason: str) -> Certification:
        cert = Certification(
            dataset_ref=dataset_ref, dbt_project_id=dbt_project_id, contract_id=contract_id,
            status=status, reason=reason,
        )
        db.add(cert)
        db.commit()
        db.refresh(cert)
        return cert

    stmt = select(QualityRule).where(QualityRule.target_table == dataset_ref, QualityRule.status == "ACTIVE")
    if dbt_project_id:
        stmt = stmt.where(QualityRule.dbt_project_id == dbt_project_id)
    rules = db.scalars(stmt).all()

    if not rules:
        return _make("UNKNOWN", "No active quality rules are registered for this dataset.")

    latest_by_rule: dict[str, QualityRuleRun] = {}
    for rule in rules:
        latest = db.scalars(
            select(QualityRuleRun)
            .where(QualityRuleRun.quality_rule_id == rule.id)
            .order_by(QualityRuleRun.executed_at.desc())
            .limit(1)
        ).first()
        if latest is not None:
            latest_by_rule[rule.id] = latest

    if not latest_by_rule:
        return _make("UNKNOWN", f"{len(rules)} active rule(s) registered, none have been executed yet.")

    failing_p1 = [
        r for r in rules if r.id in latest_by_rule and r.severity == "P1"
        and latest_by_rule[r.id].status in ("FAIL", "ERROR")
    ]
    failing_other = [
        r for r in rules if r.id in latest_by_rule and r.severity != "P1"
        and latest_by_rule[r.id].status in ("FAIL", "ERROR")
    ]

    if failing_p1:
        status, reason = "FAILED", f"P1 rule(s) failing: {', '.join(r.name for r in failing_p1)}."
    elif failing_other:
        status, reason = "AT_RISK", f"Non-critical rule(s) failing: {', '.join(r.name for r in failing_other)}."
    else:
        passed = [r.name for r in rules if r.id in latest_by_rule]
        status, reason = "CERTIFIED", f"All {len(passed)} evaluated rule(s) passed: {', '.join(passed)}."

    missing = [r.name for r in rules if r.id not in latest_by_rule]
    if missing:
        reason += f" (not yet executed: {', '.join(missing)})"

    return _make(status, reason)
