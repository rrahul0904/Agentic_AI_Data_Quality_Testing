"""Claim-Evidence Grounding Gateway (Architecture spec §11, Master Prompt §8).

This is deliberately plain, deterministic Python -- the spec's own grounding
rules are a status machine over evidence, not an LLM call. The LLM's future
job (not built yet, see docs/IMPLEMENTATION_STATUS.md) is to *generate* a
claim's candidate statement; grounding it against evidence is -- and must
stay -- pure code, so a claim's status can never be the model talking itself
into confidence.
"""

from __future__ import annotations


def compute_claim_status(
    *, supporting_evidence_count: int, contradictory_evidence_count: int, context_missing: bool = False
) -> str:
    """Architecture spec §11.3:
        Missing required context            -> BLOCK (surfaced as UNKNOWN here;
                                                 callers should refuse to act on it)
        Deterministic claim, no evidence     -> UNVERIFIED
        Contradictory evidence exists        -> CONFLICTED
        Direct reproducible evidence present -> SUPPORTED
    """
    if context_missing:
        return "UNKNOWN"
    if contradictory_evidence_count > 0:
        return "CONFLICTED"
    if supporting_evidence_count > 0:
        return "SUPPORTED"
    return "UNVERIFIED"
