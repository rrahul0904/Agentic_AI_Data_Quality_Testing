"""LLM-escalated RCA for genuinely ambiguous cases (Architecture spec §35,
Master Prompt §19 "RCA Agent"). Only called from services/rca.py when the
deterministic lineage walk finds *more than one* upstream dataset with a
failing certification -- a case a lineage walk alone can't rank.

The non-negotiable part: the LLM never gets to assert a claim's status.
It picks a root-cause candidate from a fixed whitelist (the datasets
services/rca.py already found failing) and cites evidence IDs from a fixed
whitelist (the evidence those failures actually produced). Both choices
are verified against the whitelist -- an unlisted dataset name or a made-up
evidence ID is discarded, not trusted -- before anything is persisted. The
claim's final status is computed by services/grounding.py from the
*verified* links, exactly like the deterministic path; the LLM's own
confidence is never the source of truth.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import DbtProject
from ..models_quality import AgentClaim, Certification, ClaimEvidenceLink, Evidence, LLMCallLog
from .grounding import compute_claim_status
from .llm_gateway import LLMGateway, LLMGatewayError, get_default_gateway


class RCAHypothesis(BaseModel):
    root_cause_dataset: str = Field(description="Must be exactly one of the candidate dataset names provided.")
    statement: str = Field(description="A concise, evidence-grounded explanation of why this candidate is the most likely primary root cause.")
    cited_evidence_ids: list[str] = Field(description="IDs of evidence items (from the list provided) that support this conclusion.")


def _gather_candidate_evidence(db, node_label: str, dbt_project_id: str) -> list[Evidence]:
    from .rca import _most_recent_failing_run  # local import: avoid a circular import at module load time

    run = _most_recent_failing_run(db, node_label, dbt_project_id)
    return list(run.evidence) if run else []


def _unresolved_claim(db, dataset_ref: str, candidates: list[tuple[str, Certification]], reason: str) -> AgentClaim:
    names = ", ".join(node for node, _ in candidates)
    claim = AgentClaim(
        claim_type="RCA",
        statement=(
            f"Ambiguous: {len(candidates)} upstream datasets ({names}) all have failing certifications "
            f"for '{dataset_ref}'. {reason}"
        ),
        status="UNVERIFIED",
        generated_by="deterministic_rca",
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


def escalate_ambiguous_rca(
    db,
    dbt_project: DbtProject,
    dataset_ref: str,
    chain: list[str],
    candidates: list[tuple[str, Certification]],
    llm_gateway: LLMGateway | None = None,
) -> AgentClaim:
    gateway = llm_gateway if llm_gateway is not None else get_default_gateway()

    candidate_evidence: dict[str, list[Evidence]] = {
        node: _gather_candidate_evidence(db, node, dbt_project.id) for node, _ in candidates
    }
    all_evidence_by_id = {ev.id: ev for evs in candidate_evidence.values() for ev in evs}

    if gateway is None:
        return _unresolved_claim(
            db, dataset_ref, candidates,
            "No LLM Gateway is configured to reason about which is the primary root cause -- "
            "set OPENAI_API_KEY to enable this.",
        )

    system_prompt = (
        "You are a root-cause-analysis assistant for a data pipeline. You will be given a failing dataset, "
        "its upstream lineage, and a set of candidate upstream datasets that ALL currently have failing data "
        "quality certifications. Pick the ONE candidate most likely to be the primary root cause, write a "
        "concise statement explaining why using only the evidence given, and cite the evidence IDs (from the "
        "list provided) that support your conclusion. Do not invent evidence IDs or dataset names not listed "
        "-- if you do, your citation will simply be discarded."
    )

    lines = [
        f"Target dataset (currently failing): {dataset_ref}",
        f"Lineage path: {' -> '.join(chain)}",
        "",
        "Candidate root causes:",
    ]
    for node, cert in candidates:
        lines.append(f'- {node}: certification={cert.status}, reason="{cert.reason}"')
        for ev in candidate_evidence[node]:
            lines.append(
                f"    evidence_id={ev.id} type={ev.evidence_type} value={ev.value} query={ev.query_text}"
            )
    user_prompt = "\n".join(lines)

    try:
        hypothesis, usage = gateway.generate_structured(
            system_prompt=system_prompt, user_prompt=user_prompt, response_model=RCAHypothesis
        )
    except LLMGatewayError as exc:
        return _unresolved_claim(db, dataset_ref, candidates, f"LLM escalation failed: {exc}.")

    valid_dataset_names = {node for node, _ in candidates}
    chosen = hypothesis.root_cause_dataset if hypothesis.root_cause_dataset in valid_dataset_names else None
    verified_evidence_ids = [eid for eid in hypothesis.cited_evidence_ids if eid in all_evidence_by_id]

    statement = hypothesis.statement
    if chosen is None:
        statement = f"[LLM cited an unlisted dataset '{hypothesis.root_cause_dataset}', discarded] {statement}"

    claim = AgentClaim(
        claim_type="RCA", statement=statement, generated_by=f"rca_agent:{usage.provider}:{usage.model}",
        status="UNKNOWN",
    )
    db.add(claim)
    db.flush()

    for eid in verified_evidence_ids:
        db.add(ClaimEvidenceLink(claim_id=claim.id, evidence_id=eid, relationship_type="SUPPORTING"))

    claim.status = compute_claim_status(
        supporting_evidence_count=len(verified_evidence_ids), contradictory_evidence_count=0
    )
    db.add(
        LLMCallLog(
            agent_claim_id=claim.id, purpose="rca_ambiguous_upstream",
            provider=usage.provider, model=usage.model, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out,
        )
    )
    db.commit()
    db.refresh(claim)
    return claim
