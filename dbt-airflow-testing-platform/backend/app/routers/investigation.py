from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DbtProject
from ..models_quality import AgentClaim, RemediationProposal
from ..schemas_quality import (
    AgentClaimOut,
    RemediationProposalCreate,
    RemediationProposalOut,
)
from ..services.rca import locate_root_cause
from ..services.remediation import RemediationError, apply_remediation, build_proposed_change

router = APIRouter(prefix="/api", tags=["investigation"])


@router.post("/rca", response_model=AgentClaimOut)
def run_rca(
    dbt_project_id: str = Query(...), dataset_ref: str = Query(...), db: Session = Depends(get_db)
):
    project = db.get(DbtProject, dbt_project_id)
    if project is None:
        raise HTTPException(404, "dbt project not found")
    return locate_root_cause(db, project, dataset_ref)


@router.get("/agent-claims", response_model=list[AgentClaimOut])
def list_agent_claims(db: Session = Depends(get_db)):
    return db.scalars(select(AgentClaim).order_by(AgentClaim.created_at.desc())).all()


@router.get("/agent-claims/{claim_id}", response_model=AgentClaimOut)
def get_agent_claim(claim_id: str, db: Session = Depends(get_db)):
    claim = db.get(AgentClaim, claim_id)
    if claim is None:
        raise HTTPException(404, "claim not found")
    return claim


@router.post("/remediation-proposals", response_model=RemediationProposalOut, status_code=201)
def create_remediation_proposal(payload: RemediationProposalCreate, db: Session = Depends(get_db)):
    claim = db.get(AgentClaim, payload.claim_id)
    if claim is None:
        raise HTTPException(404, "claim not found")
    proposal = RemediationProposal(
        claim_id=payload.claim_id,
        target_file=payload.target_file,
        proposed_change=build_proposed_change(payload.find_text, payload.replace_text),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


@router.get("/remediation-proposals", response_model=list[RemediationProposalOut])
def list_remediation_proposals(db: Session = Depends(get_db)):
    return db.scalars(select(RemediationProposal).order_by(RemediationProposal.created_at.desc())).all()


@router.post("/remediation-proposals/{proposal_id}/approve", response_model=RemediationProposalOut)
def approve_remediation_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(RemediationProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "proposal not found")
    if proposal.status != "PROPOSED":
        raise HTTPException(422, f"proposal is '{proposal.status}', not 'PROPOSED'")
    proposal.status = "APPROVED"
    db.commit()
    db.refresh(proposal)
    return proposal


def _resolve_project_for_proposal(db: Session, proposal: RemediationProposal) -> DbtProject:
    """A proposal targets a file, not a project directly -- resolve via the
    claim's linked evidence back to the dbt project the evidence came from."""
    for link in proposal.claim.evidence_links:
        rule_run = link.evidence.rule_run if link.evidence else None
        if rule_run is not None and rule_run.rule.dbt_project_id:
            project = db.get(DbtProject, rule_run.rule.dbt_project_id)
            if project is not None:
                return project
    raise HTTPException(422, "could not resolve a dbt project from this proposal's linked evidence")


@router.post("/remediation-proposals/{proposal_id}/apply", response_model=RemediationProposalOut)
def apply_remediation_proposal(proposal_id: str, db: Session = Depends(get_db)):
    proposal = db.get(RemediationProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "proposal not found")

    project = _resolve_project_for_proposal(db, proposal)
    try:
        apply_remediation(proposal, project)
    except RemediationError as exc:
        raise HTTPException(422, str(exc)) from exc

    proposal.status = "APPLIED"
    proposal.applied_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(proposal)
    return proposal
