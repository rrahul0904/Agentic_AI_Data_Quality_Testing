from __future__ import annotations

from agentic_data_platform.governance.engine import (
    classify_metadata_columns,
    pii_exposure,
    pii_policy_check,
    propagate_pii,
    sensitive_access_report,
)
from agentic_data_platform.governance.pii import classify_column
from agentic_data_platform.governance.rbac import (
    build_rbac_graph,
    excessive_privileges,
    object_access,
    reachable_access,
)


def test_pii_classifier_uses_name_and_sample_evidence_without_false_credit_card():
    email = classify_column("guest_email")
    assert email[0]["category"] == "email"
    assert email[0]["confidence"] >= 0.8

    card = classify_column("payment_value", sample_values=["4111111111111111", "4242424242424242"])
    assert card[0]["category"] == "credit_card"

    not_card = classify_column("payment_value", sample_values=["1234567890123456", "9999999999999999"])
    assert all(item["category"] != "credit_card" for item in not_card)


def test_pii_propagates_through_multihop_column_lineage():
    graph = {
        "nodes": [
            {"node_id": "source.raw.guests.email", "resource_type": "source"},
            {"node_id": "model.stg_guests.email", "resource_type": "model"},
            {"node_id": "model.dim_guest.email", "resource_type": "model"},
            {"node_id": "model.mart_guest.email", "resource_type": "mart"},
        ],
        "edges": [
            {"source": "source.raw.guests.email", "target": "model.stg_guests.email"},
            {"source": "model.stg_guests.email", "target": "model.dim_guest.email"},
            {"source": "model.dim_guest.email", "target": "model.mart_guest.email"},
        ],
    }
    findings = [{
        "node_id": "source.raw.guests.email",
        "category": "email",
        "confidence": 0.95,
        "evidence": ["column name"],
    }]
    result = propagate_pii(graph, findings)
    assert result["propagated_count"] == 3
    mart = [item for item in result["findings"] if item["node_id"] == "model.mart_guest.email"][0]
    assert mart["depth"] == 3
    exposure = pii_exposure(graph, findings)
    assert exposure["status"] == "WARN"
    assert any(item["node_id"] == "model.mart_guest.email" for item in exposure["exposures"])


def test_query_policy_blocks_disallowed_pii_and_respects_allowlist():
    schema = {
        "raw.guests": {
            "guest_id": {"data_type": "INTEGER"},
            "guest_email": {"data_type": "VARCHAR"},
        }
    }
    blocked = pii_policy_check("SELECT guest_email FROM raw.guests", schema)
    assert blocked["status"] == "BLOCK"
    allowed = pii_policy_check(
        "SELECT guest_email FROM raw.guests",
        schema,
        allow_categories=["email"],
    )
    assert allowed["status"] == "PASS"


def test_rbac_graph_reachable_access_sensitive_access_and_excessive_privileges():
    metadata = {
        "roles": [{"name": "ANALYST"}, {"name": "PII_READER"}],
        "role_grants": [
            {"grantee_name": "ANALYST", "role": "PII_READER"},
            {
                "grantee_name": "PII_READER",
                "granted_on": "TABLE",
                "name": "MART_GUEST",
                "privilege": "SELECT",
            },
        ],
        "user_grants": [{"grantee_name": "RAHUL", "role": "ANALYST"}],
    }
    graph = build_rbac_graph(metadata)
    access = reachable_access(graph, "user", "RAHUL")
    assert access["access_count"] == 1
    assert access["access"][0]["node"]["name"] == "MART_GUEST"

    objects = object_access(graph, "MART_GUEST")
    assert any(item["principal"]["name"] == "RAHUL" for item in objects["principals"])

    sensitive = sensitive_access_report(
        graph,
        [{"object_name": "MART_GUEST", "column": "EMAIL", "category": "email"}],
    )
    assert sensitive["status"] == "WARN"
    assert sensitive["summary"]["principals_with_sensitive_access"] >= 1

    excessive = excessive_privileges(
        graph,
        observed_objects_by_principal={"user:rahul": []},
        minimum_grants=1,
        unused_ratio_threshold=1.0,
    )
    assert excessive["status"] == "WARN"


def test_metadata_classification_returns_persistable_shape():
    result = classify_metadata_columns(
        [
            {
                "object_id": "local:main:guests",
                "column_name": "guest_email",
                "data_type": "TEXT",
                "comment": "Guest email address",
            }
        ]
    )
    assert result["classification_count"] >= 1
    assert result["findings"][0]["object_id"] == "local:main:guests"
