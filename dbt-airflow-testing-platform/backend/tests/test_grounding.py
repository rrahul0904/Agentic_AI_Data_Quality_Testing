from app.services.grounding import compute_claim_status


def test_no_evidence_is_unverified():
    assert compute_claim_status(supporting_evidence_count=0, contradictory_evidence_count=0) == "UNVERIFIED"


def test_supporting_evidence_is_supported():
    assert compute_claim_status(supporting_evidence_count=1, contradictory_evidence_count=0) == "SUPPORTED"


def test_contradictory_evidence_wins_even_with_support():
    assert compute_claim_status(supporting_evidence_count=2, contradictory_evidence_count=1) == "CONFLICTED"


def test_missing_context_forces_unknown_regardless_of_evidence():
    assert (
        compute_claim_status(supporting_evidence_count=5, contradictory_evidence_count=0, context_missing=True)
        == "UNKNOWN"
    )
