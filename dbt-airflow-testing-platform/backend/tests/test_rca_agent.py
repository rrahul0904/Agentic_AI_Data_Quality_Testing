import json

from app.models import DbtProject
from app.models_quality import Certification, Evidence, LLMCallLog, QualityRule, QualityRuleRun
from app.services.llm_gateway import LLMGateway, LLMGatewayError, LLMUsage
from app.services.rca import locate_root_cause
from app.services.rca_agent import RCAHypothesis, escalate_ambiguous_rca

LINEAGE = {
    "nodes": [
        {"id": "model.p.stg_a", "label": "stg_a", "kind": "model"},
        {"id": "model.p.stg_b", "label": "stg_b", "kind": "model"},
        {"id": "model.p.fact", "label": "fact", "kind": "model"},
    ],
    "edges": [
        {"from": "model.p.stg_a", "to": "model.p.fact"},
        {"from": "model.p.stg_b", "to": "model.p.fact"},
    ],
}


class FakeLLMGateway(LLMGateway):
    def __init__(self, response, tokens_in=10, tokens_out=20):
        self.response = response
        self.usage = LLMUsage(provider="fake", model="fake-model", tokens_in=tokens_in, tokens_out=tokens_out)
        self.calls = 0

    def generate_structured(self, *, system_prompt, user_prompt, response_model):
        self.calls += 1
        return self.response, self.usage


class RaisingLLMGateway(LLMGateway):
    def generate_structured(self, *, system_prompt, user_prompt, response_model):
        raise LLMGatewayError("simulated provider outage")


def _make_project(db) -> DbtProject:
    project = DbtProject(
        name="ambiguous project", execution_mode="local", adapter="duckdb",
        venv_path="/tmp/venv", project_dir="/tmp/project", profiles_dir="/tmp/project/profiles",
        lineage_json=json.dumps(LINEAGE), status="READY",
    )
    db.add(project)
    db.commit()
    return project


def _fail_dataset(db, project, dataset_ref: str, rule_name: str) -> Evidence:
    rule = QualityRule(
        dbt_project_id=project.id, name=rule_name, dimension="accuracy", rule_type="custom_sql",
        target_table=dataset_ref, severity="P1",
    )
    db.add(rule)
    db.flush()
    run = QualityRuleRun(quality_rule_id=rule.id, status="FAIL", measured_value=1.0)
    db.add(run)
    db.flush()
    ev = Evidence(
        quality_rule_run_id=run.id, evidence_type="QUERY_RESULT", source_type="duckdb",
        dataset_ref=dataset_ref, value="1.0",
    )
    db.add(ev)
    db.add(
        Certification(
            dataset_ref=dataset_ref, dbt_project_id=project.id, status="FAILED",
            reason=f"P1 rule(s) failing: {rule_name}.",
        )
    )
    db.commit()
    db.refresh(ev)
    return ev


def test_locate_root_cause_escalates_when_two_upstream_datasets_fail(db_session):
    project = _make_project(db_session)
    ev_a = _fail_dataset(db_session, project, "stg_a", "a-rule")
    _fail_dataset(db_session, project, "stg_b", "b-rule")

    fake = FakeLLMGateway(RCAHypothesis(root_cause_dataset="stg_a", statement="stg_a looks primary", cited_evidence_ids=[ev_a.id]))
    claim = locate_root_cause(db_session, project, "fact", llm_gateway=fake)

    assert fake.calls == 1
    assert claim.generated_by.startswith("rca_agent:")
    assert claim.status == "SUPPORTED"
    assert len(claim.evidence_links) == 1


def test_escalation_discards_hallucinated_dataset_name(db_session):
    project = _make_project(db_session)
    ev_a = _fail_dataset(db_session, project, "stg_a", "a-rule")
    _fail_dataset(db_session, project, "stg_b", "b-rule")
    chain = ["stg_a", "stg_b", "fact"]
    from app.services.rca import find_failing_upstream_nodes

    real_candidates = find_failing_upstream_nodes(db_session, chain, "fact", project.id)

    fake = FakeLLMGateway(
        RCAHypothesis(root_cause_dataset="not_a_real_dataset", statement="bogus", cited_evidence_ids=[ev_a.id])
    )
    claim = escalate_ambiguous_rca(db_session, project, "fact", chain, real_candidates, fake)

    assert "unlisted dataset" in claim.statement
    # the cited evidence was still real, so it's still linked/grounded
    assert claim.status == "SUPPORTED"


def test_escalation_discards_hallucinated_evidence_ids(db_session):
    project = _make_project(db_session)
    _fail_dataset(db_session, project, "stg_a", "a-rule")
    _fail_dataset(db_session, project, "stg_b", "b-rule")
    chain = ["stg_a", "stg_b", "fact"]
    from app.services.rca import find_failing_upstream_nodes

    candidates = find_failing_upstream_nodes(db_session, chain, "fact", project.id)

    fake = FakeLLMGateway(
        RCAHypothesis(root_cause_dataset="stg_a", statement="stg_a", cited_evidence_ids=["made-up-id-1", "made-up-id-2"])
    )
    claim = escalate_ambiguous_rca(db_session, project, "fact", chain, candidates, fake)

    assert claim.evidence_links == []
    assert claim.status == "UNVERIFIED"  # LLM said "supported"; grounding disagrees because nothing verified


def test_escalation_falls_back_cleanly_on_gateway_error(db_session):
    project = _make_project(db_session)
    _fail_dataset(db_session, project, "stg_a", "a-rule")
    _fail_dataset(db_session, project, "stg_b", "b-rule")
    chain = ["stg_a", "stg_b", "fact"]
    from app.services.rca import find_failing_upstream_nodes

    candidates = find_failing_upstream_nodes(db_session, chain, "fact", project.id)

    claim = escalate_ambiguous_rca(db_session, project, "fact", chain, candidates, RaisingLLMGateway())

    assert claim.generated_by == "deterministic_rca"
    assert claim.status == "UNVERIFIED"
    assert "simulated provider outage" in claim.statement


def test_escalation_with_no_gateway_configured_is_unverified_not_a_crash(db_session):
    project = _make_project(db_session)
    _fail_dataset(db_session, project, "stg_a", "a-rule")
    _fail_dataset(db_session, project, "stg_b", "b-rule")
    chain = ["stg_a", "stg_b", "fact"]
    from app.services.rca import find_failing_upstream_nodes

    candidates = find_failing_upstream_nodes(db_session, chain, "fact", project.id)

    claim = escalate_ambiguous_rca(db_session, project, "fact", chain, candidates, llm_gateway=None)

    assert claim.status == "UNVERIFIED"
    assert claim.generated_by == "deterministic_rca"


def test_llm_call_is_logged_for_cost_accounting(db_session):
    project = _make_project(db_session)
    ev_a = _fail_dataset(db_session, project, "stg_a", "a-rule")
    _fail_dataset(db_session, project, "stg_b", "b-rule")
    chain = ["stg_a", "stg_b", "fact"]
    from app.services.rca import find_failing_upstream_nodes

    candidates = find_failing_upstream_nodes(db_session, chain, "fact", project.id)
    fake = FakeLLMGateway(RCAHypothesis(root_cause_dataset="stg_a", statement="x", cited_evidence_ids=[ev_a.id]))

    claim = escalate_ambiguous_rca(db_session, project, "fact", chain, candidates, fake)

    logs = db_session.query(LLMCallLog).filter(LLMCallLog.agent_claim_id == claim.id).all()
    assert len(logs) == 1
    assert logs[0].tokens_in == 10 and logs[0].tokens_out == 20 and logs[0].provider == "fake"
