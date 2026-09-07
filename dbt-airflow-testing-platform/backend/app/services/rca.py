"""Evidence-grounded root cause localization (Architecture spec §35).

The primary path here is deliberately NOT an LLM call: this walks the
*real* dbt lineage graph already captured for the project
(services/lineage.py) and the *real* certification/evidence history already
persisted by the Quality Rule Engine. When exactly one upstream dataset is
failing, the lineage walk alone gives an unambiguous, grounded answer --
no LLM needed. Only when the walk finds *more than one* upstream dataset
failing at once (genuine ambiguity a deterministic walk can't resolve on
its own) does this escalate to the LLM-backed RCA agent
(services/rca_agent.py), which still can't assert a claim's status itself
-- see that module's docstring.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DbtProject
from ..models_quality import AgentClaim, Certification, ClaimEvidenceLink, QualityRule, QualityRuleRun
from .grounding import compute_claim_status
from .llm_gateway import LLMGateway


def get_upstream_chain(lineage: dict, target_label: str) -> list[str]:
    """Returns model labels in upstream-first order, ending with
    `target_label` itself (or just `[target_label]` if it isn't in the
    lineage graph, e.g. a mart with no captured dbt lineage)."""
    nodes = lineage.get("nodes", [])
    edges = lineage.get("edges", [])

    id_by_label = {n["label"]: n["id"] for n in nodes if n.get("kind") == "model"}
    label_by_id = {v: k for k, v in id_by_label.items()}
    target_id = id_by_label.get(target_label)
    if not target_id:
        return [target_label]

    parents: dict[str, list[str]] = {}
    for e in edges:
        parents.setdefault(e["to"], []).append(e["from"])

    ancestors: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in ancestors:
            return
        ancestors.add(node_id)
        for p in parents.get(node_id, []):
            visit(p)

    visit(target_id)
    model_ancestors = [i for i in ancestors if i in label_by_id]

    def depth(node_id: str) -> int:
        seen: set[str] = set()

        def go(n: str) -> None:
            if n in seen:
                return
            seen.add(n)
            for p in parents.get(n, []):
                go(p)

        go(node_id)
        return len(seen)

    model_ancestors.sort(key=depth)
    return [label_by_id[i] for i in model_ancestors]


def _latest_certification(db: Session, dataset_ref: str, dbt_project_id: str) -> Certification | None:
    return db.scalars(
        select(Certification)
        .where(Certification.dataset_ref == dataset_ref, Certification.dbt_project_id == dbt_project_id)
        .order_by(Certification.evaluated_at.desc())
        .limit(1)
    ).first()


def find_failing_upstream_nodes(
    db: Session, chain: list[str], dataset_ref: str, dbt_project_id: str
) -> list[tuple[str, Certification]]:
    """All upstream nodes (excluding the target itself) whose most recent
    certification is FAILED/AT_RISK -- zero means nothing to blame upstream,
    exactly one is an unambiguous deterministic answer, more than one is the
    genuine-ambiguity case that gets escalated to the LLM agent."""
    results = []
    for node_label in chain:
        if node_label == dataset_ref:
            continue
        cert = _latest_certification(db, node_label, dbt_project_id)
        if cert is not None and cert.status in ("FAILED", "AT_RISK"):
            results.append((node_label, cert))
    return results


def _most_recent_failing_run(db: Session, dataset_ref: str, dbt_project_id: str) -> QualityRuleRun | None:
    rule_ids = db.scalars(
        select(QualityRule.id).where(
            QualityRule.target_table == dataset_ref, QualityRule.dbt_project_id == dbt_project_id
        )
    ).all()
    if not rule_ids:
        return None
    return db.scalars(
        select(QualityRuleRun)
        .where(QualityRuleRun.quality_rule_id.in_(rule_ids), QualityRuleRun.status.in_(["FAIL", "ERROR"]))
        .order_by(QualityRuleRun.executed_at.desc())
        .limit(1)
    ).first()


def locate_root_cause(
    db: Session, dbt_project: DbtProject, dataset_ref: str, llm_gateway: LLMGateway | None = None
) -> AgentClaim:
    """Walks upstream from `dataset_ref` via the project's captured dbt
    lineage. Zero failing upstream datasets -> UNVERIFIED (nothing to
    ground a claim in). Exactly one -> an unambiguous deterministic claim,
    grounded in that dataset's actual failing-rule evidence. More than one
    -> escalates to the LLM RCA agent (services/rca_agent.py), since a
    lineage walk alone can't rank multiple simultaneous upstream failures.

    `llm_gateway` is only used in the ambiguous branch; pass a fake in
    tests to avoid a real API call, or leave it None to use whatever's
    configured (see llm_gateway.get_default_gateway)."""
    lineage = json.loads(dbt_project.lineage_json or '{"nodes": [], "edges": []}')
    chain = get_upstream_chain(lineage, dataset_ref)  # upstream-first, ends at dataset_ref
    candidates = find_failing_upstream_nodes(db, chain, dataset_ref, dbt_project.id)

    if not candidates:
        # No upstream dataset has a failing certification on record -- the
        # defect (if any) is local to `dataset_ref` itself, or evidence is
        # simply missing upstream. Either way, don't guess.
        claim = AgentClaim(
            claim_type="RCA",
            statement=(
                f"No upstream dataset in the lineage for '{dataset_ref}' has a failing certification on "
                f"record. If '{dataset_ref}' itself is failing, the cause is local to it, or upstream "
                f"datasets haven't been certified yet."
            ),
            status="UNVERIFIED",
            generated_by="deterministic_rca",
        )
        db.add(claim)
        db.commit()
        db.refresh(claim)
        return claim

    if len(candidates) > 1:
        from .rca_agent import escalate_ambiguous_rca

        return escalate_ambiguous_rca(db, dbt_project, dataset_ref, chain, candidates, llm_gateway)

    root_node, root_cert = candidates[0]
    failing_run = _most_recent_failing_run(db, root_node, dbt_project.id)
    statement = (
        f"The discrepancy observed at '{dataset_ref}' traces to '{root_node}': {root_cert.reason} "
        f"(lineage path: {' -> '.join(chain)})."
    )
    claim = AgentClaim(claim_type="RCA", statement=statement, generated_by="deterministic_rca", status="UNKNOWN")
    db.add(claim)
    db.flush()

    supporting = 0
    if failing_run is not None:
        for ev in failing_run.evidence:
            db.add(ClaimEvidenceLink(claim_id=claim.id, evidence_id=ev.id, relationship_type="SUPPORTING"))
            supporting += 1

    claim.status = compute_claim_status(supporting_evidence_count=supporting, contradictory_evidence_count=0)
    db.commit()
    db.refresh(claim)
    return claim
