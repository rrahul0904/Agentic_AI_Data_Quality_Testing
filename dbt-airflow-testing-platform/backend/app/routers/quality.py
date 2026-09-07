from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DbtProject
from ..models_quality import (
    BusinessConcept,
    Certification,
    Evidence,
    Incident,
    QualityContract,
    QualityRule,
    QualityRuleRun,
)
from ..schemas_quality import (
    BusinessConceptCreate,
    BusinessConceptOut,
    CertificationOut,
    CompiledRuleOut,
    IncidentOut,
    QualityContractCreate,
    QualityContractOut,
    QualityRuleCreate,
    QualityRuleOut,
    QualityRuleRunOut,
)
from ..services.adapters.duckdb_adapter import resolve_duckdb_adapter_for_project
from ..services.certification import evaluate_certification
from ..services.quality_rule_engine import RuleCompilationError, compile_rule, execute_rule

router = APIRouter(prefix="/api", tags=["quality"])


# ---------------------------------------------------------------------------
# Business concepts
# ---------------------------------------------------------------------------


@router.post("/business-concepts", response_model=BusinessConceptOut, status_code=201)
def create_business_concept(payload: BusinessConceptCreate, db: Session = Depends(get_db)):
    concept = BusinessConcept(**payload.model_dump())
    db.add(concept)
    db.commit()
    db.refresh(concept)
    return concept


@router.get("/business-concepts", response_model=list[BusinessConceptOut])
def list_business_concepts(db: Session = Depends(get_db)):
    return db.scalars(select(BusinessConcept).order_by(BusinessConcept.created_at.desc())).all()


# ---------------------------------------------------------------------------
# Quality contracts
# ---------------------------------------------------------------------------


@router.post("/quality-contracts", response_model=QualityContractOut, status_code=201)
def create_quality_contract(payload: QualityContractCreate, db: Session = Depends(get_db)):
    contract = QualityContract(**payload.model_dump())
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


@router.get("/quality-contracts", response_model=list[QualityContractOut])
def list_quality_contracts(db: Session = Depends(get_db)):
    return db.scalars(select(QualityContract).order_by(QualityContract.created_at.desc())).all()


@router.get("/quality-contracts/{contract_id}", response_model=QualityContractOut)
def get_quality_contract(contract_id: str, db: Session = Depends(get_db)):
    contract = db.get(QualityContract, contract_id)
    if contract is None:
        raise HTTPException(404, "quality contract not found")
    return contract


# ---------------------------------------------------------------------------
# Quality rules
# ---------------------------------------------------------------------------


@router.post("/quality-rules", response_model=QualityRuleOut, status_code=201)
def create_quality_rule(payload: QualityRuleCreate, db: Session = Depends(get_db)):
    rule = QualityRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/quality-rules", response_model=list[QualityRuleOut])
def list_quality_rules(dbt_project_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(QualityRule).order_by(QualityRule.created_at.desc())
    if dbt_project_id:
        stmt = stmt.where(QualityRule.dbt_project_id == dbt_project_id)
    return db.scalars(stmt).all()


@router.get("/quality-rules/{rule_id}", response_model=QualityRuleOut)
def get_quality_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(404, "quality rule not found")
    return rule


@router.get("/quality-rules/{rule_id}/compile", response_model=CompiledRuleOut)
def compile_quality_rule(rule_id: str, dialect: str = Query("duckdb"), db: Session = Depends(get_db)):
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(404, "quality rule not found")
    try:
        sql = compile_rule(rule, target_dialect=dialect)
    except RuleCompilationError as exc:
        raise HTTPException(422, str(exc)) from exc
    return CompiledRuleOut(dialect=dialect, sql=sql)


def _resolve_adapter_or_422(db: Session, rule: QualityRule):
    if not rule.dbt_project_id:
        raise HTTPException(422, "rule has no dbt_project_id; cannot resolve a warehouse adapter")
    project = db.get(DbtProject, rule.dbt_project_id)
    if project is None:
        raise HTTPException(404, "the rule's dbt project no longer exists")
    if project.adapter != "duckdb":
        raise HTTPException(
            422,
            f"only the DuckDB adapter executes for real in this phase; project adapter is '{project.adapter}'",
        )
    try:
        return resolve_duckdb_adapter_for_project(project)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc)) from exc


def _execute_and_persist(db: Session, rule: QualityRule, adapter) -> QualityRuleRun:
    outcome = execute_rule(rule, adapter)

    run = QualityRuleRun(
        quality_rule_id=rule.id,
        status=outcome.status,
        measured_value=outcome.measured_value,
        compiled_sql=outcome.compiled_sql,
        dialect=outcome.dialect,
        message=outcome.message,
    )
    db.add(run)
    db.flush()
    for ev in outcome.evidence:
        db.add(
            Evidence(
                quality_rule_run_id=run.id,
                evidence_type=ev["evidence_type"],
                source_type=adapter.dialect,
                dataset_ref=ev["dataset_ref"],
                value=ev["value"],
                query_text=ev["query_text"],
                provenance_json={"adapter": adapter.dialect, "warehouse_path": adapter.warehouse_path},
            )
        )

    if run.status in ("FAIL", "ERROR") and rule.severity == "P1":
        db.add(
            Incident(
                quality_rule_id=rule.id,
                severity=rule.severity,
                dataset_ref=rule.target_table,
                title=f"{rule.name} {run.status.lower()} on {rule.target_table}",
                description=run.message,
            )
        )

    db.commit()
    db.refresh(run)
    return run


@router.post("/quality-rules/{rule_id}/execute", response_model=QualityRuleRunOut)
def execute_quality_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(404, "quality rule not found")
    adapter = _resolve_adapter_or_422(db, rule)
    return _execute_and_persist(db, rule, adapter)


@router.post("/dbt-projects/{project_id}/quality/recheck")
def recheck_project_quality(project_id: str, db: Session = Depends(get_db)):
    """Convenience for the UI: execute every ACTIVE rule for this project,
    then re-evaluate certification for every distinct dataset those rules
    target -- the "re-run quality checks" single-button flow, instead of the
    caller doing N execute calls + M certification calls by hand."""
    project = db.get(DbtProject, project_id)
    if project is None:
        raise HTTPException(404, "dbt project not found")

    rules = db.scalars(
        select(QualityRule).where(QualityRule.dbt_project_id == project_id, QualityRule.status == "ACTIVE")
    ).all()
    if not rules:
        return {"rule_runs": [], "certifications": []}

    adapter = _resolve_adapter_or_422(db, rules[0])
    runs = [_execute_and_persist(db, rule, adapter) for rule in rules]

    dataset_refs = sorted({r.target_table for r in rules})
    certifications = [evaluate_certification(db, ds, dbt_project_id=project_id) for ds in dataset_refs]

    return {
        "rule_runs": [QualityRuleRunOut.model_validate(r) for r in runs],
        "certifications": [CertificationOut.model_validate(c) for c in certifications],
    }


@router.get("/quality-rules/{rule_id}/runs", response_model=list[QualityRuleRunOut])
def list_quality_rule_runs(rule_id: str, db: Session = Depends(get_db)):
    return db.scalars(
        select(QualityRuleRun)
        .where(QualityRuleRun.quality_rule_id == rule_id)
        .order_by(QualityRuleRun.executed_at.desc())
    ).all()


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


@router.get("/incidents", response_model=list[IncidentOut])
def list_incidents(status_filter: str | None = Query(None, alias="status"), db: Session = Depends(get_db)):
    stmt = select(Incident).order_by(Incident.created_at.desc())
    if status_filter:
        stmt = stmt.where(Incident.status == status_filter)
    return db.scalars(stmt).all()


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------


@router.post("/certifications/evaluate", response_model=CertificationOut)
def evaluate_certification_endpoint(
    dataset_ref: str = Query(...),
    contract_id: str | None = Query(None),
    dbt_project_id: str | None = Query(None, description="Strongly recommended -- see evaluate_certification()"),
    db: Session = Depends(get_db),
):
    return evaluate_certification(db, dataset_ref, contract_id, dbt_project_id)


@router.get("/certifications", response_model=list[CertificationOut])
def list_certifications(
    dataset_ref: str | None = None, dbt_project_id: str | None = None, db: Session = Depends(get_db)
):
    stmt = select(Certification).order_by(Certification.evaluated_at.desc())
    if dataset_ref:
        stmt = stmt.where(Certification.dataset_ref == dataset_ref)
    if dbt_project_id:
        stmt = stmt.where(Certification.dbt_project_id == dbt_project_id)
    return db.scalars(stmt).all()
