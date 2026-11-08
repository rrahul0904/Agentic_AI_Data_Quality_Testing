"""Offline unit tests for the governance slice; no database or model credentials."""
import sqlite3

import pytest

from agentic_data_platform.semantic.ontology_review import (
    OntologyReviewLedger, draft_term_candidates, schema_fingerprint,
)


class RegistryStub:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.resource = {
            "resource_id": "demo", "elements": [
                {"kind": "metric", "name": "revenue", "parent": "orders", "description": "Net revenue",
                 "expression": "SUM(net_amount)", "data_type": "NUMBER", "metadata": {"synonyms": ["sales"]}},
                {"kind": "dimension", "name": "region", "parent": "customers", "description": "Customer region",
                 "expression": "region", "data_type": "TEXT", "metadata": {}},
            ],
            "relationships": [{"name": "orders_customer", "left_table": "orders", "right_table": "customers",
                               "expression": "orders.customer_id=customers.customer_id"}],
        }

    def show(self, name):
        if name != "demo":
            raise KeyError(name)
        return self.resource


@pytest.fixture
def context():
    registry = RegistryStub()
    signature = schema_fingerprint([
        {"table": "orders", "column": "net_amount", "data_type": "DECIMAL"},
        {"table": "customers", "column": "region", "data_type": "TEXT"},
    ])
    return registry, OntologyReviewLedger(registry), signature


def approve(ledger, signature, kind="metric", name="revenue", parent="orders"):
    return ledger.record_review("demo", kind=kind, name=name, parent=parent, reviewer="manual-reviewer",
                                evidence_ref="review-ticket-123", source_sha256=signature)


def test_source_fingerprint_is_order_insensitive_and_validates_columns():
    a = [{"table": "t", "column": "x", "data_type": "INT"},
         {"table": "t", "column": "y", "data_type": "TEXT"}]
    assert schema_fingerprint(a) == schema_fingerprint(list(reversed(a)))
    with pytest.raises(ValueError):
        schema_fingerprint([])
    with pytest.raises(ValueError):
        schema_fingerprint([{"table": "x"}])


def test_candidate_extraction_does_not_certify():
    result = draft_term_candidates([{"table": "fact_sales", "column": "net_revenue"}])
    assert result[0]["term"] == "net revenue"
    assert result[0]["status"] == "HYPOTHESIS"


def test_review_provenance_is_required(context):
    _, ledger, fingerprint = context
    with pytest.raises(ValueError):
        ledger.record_review("demo", kind="metric", name="revenue", parent="orders",
                             reviewer="", evidence_ref="ticket", source_sha256=fingerprint)
    with pytest.raises(ValueError):
        ledger.record_review("demo", kind="metric", name="revenue", parent="orders",
                             reviewer="alice", evidence_ref="", source_sha256=fingerprint)


def test_no_auto_certification(context):
    _, ledger, fp = context
    assert ledger.gate("demo", requested_concepts=["revenue"], current_source_sha256=fp)["reason"] == "UNREVIEWED"


def test_exact_and_synonym_require_review(context):
    _, ledger, fp = context
    approve(ledger, fp)
    assert ledger.gate("demo", requested_concepts=["revenue"], current_source_sha256=fp)["status"] == "READY_FOR_SQL_VALIDATION"
    assert ledger.gate("demo", requested_concepts=["sales"], current_source_sha256=fp)["status"] == "READY_FOR_SQL_VALIDATION"


def test_unknown_question_cannot_be_answered(context):
    _, ledger, fp = context
    approve(ledger, fp)
    assert ledger.gate("demo", requested_concepts=["ad spend"], current_source_sha256=fp)["reason"] == "UNKNOWN_CONCEPT"


def test_unverified_metric_definition_change_stales_review(context):
    registry, ledger, fp = context
    approve(ledger, fp)
    registry.resource["elements"][0]["expression"] = "SUM(gross_amount)"
    assert ledger.gate("demo", requested_concepts=["revenue"], current_source_sha256=fp)["reason"] == "STALE"


def test_source_schema_change_stales_review(context):
    _, ledger, fp = context
    approve(ledger, fp)
    changed = schema_fingerprint([{"table": "orders", "column": "net_amount", "data_type": "FLOAT"}])
    assert ledger.gate("demo", requested_concepts=["revenue"], current_source_sha256=changed)["reason"] == "STALE"


def test_cross_table_join_requires_reviewed_path(context):
    _, ledger, fp = context
    approve(ledger, fp)
    approve(ledger, fp, "dimension", "region", "customers")
    blocked = ledger.gate("demo", requested_concepts=["revenue", "region"], current_source_sha256=fp)
    assert blocked["reason"] == "JOIN_PATH_NOT_DECLARED"
    unreviewed = ledger.gate("demo", requested_concepts=["revenue", "region"],
                             required_relationships=["orders_customer"], current_source_sha256=fp)
    assert unreviewed["reason"] == "UNREVIEWED"
    approve(ledger, fp, "relationship", "orders_customer", None)
    allowed = ledger.gate("demo", requested_concepts=["revenue", "region"],
                          required_relationships=["orders_customer"], current_source_sha256=fp)
    assert allowed["status"] == "READY_FOR_SQL_VALIDATION"


def test_unknown_relationship_blocked(context):
    _, ledger, fp = context
    approve(ledger, fp)
    result = ledger.gate("demo", requested_concepts=["revenue"],
                         required_relationships=["nonexistent"], current_source_sha256=fp)
    assert result["reason"] == "UNKNOWN_RELATIONSHIP"


def test_empty_request_fails_closed(context):
    _, ledger, fp = context
    assert ledger.gate("demo", requested_concepts=[], current_source_sha256=fp)["reason"] == "MISSING_CONCEPTS_OR_FRESH_SCHEMA_EVIDENCE"


def test_ambiguous_synonym_fails_closed(context):
    registry, ledger, fp = context
    registry.resource["elements"][1]["metadata"]["synonyms"] = ["sales"]
    assert ledger.gate("demo", requested_concepts=["sales"], current_source_sha256=fp)["reason"] == "AMBIGUOUS_CONCEPT"


def test_unrecognized_review_object_fails(context):
    _, ledger, fp = context
    with pytest.raises(KeyError):
        approve(ledger, fp, "metric", "fake", "orders")
