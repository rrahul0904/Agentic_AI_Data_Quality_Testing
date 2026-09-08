from __future__ import annotations

import json

from agentic_data_platform.review import (
    change_impact,
    deliver_github_review,
    deliver_gitlab_review,
    deployment_risk,
    recommended_tests,
    review_dbt_changes,
)


def _project(tmp_path, *, failing_test: bool = False):
    project = tmp_path / "dbt"
    target = project / "target"
    target.mkdir(parents=True)
    (project / "dbt_project.yml").write_text("name: demo\nversion: '1.0'\nprofile: demo\n")

    model_id = "model.demo.fact_orders"
    test_id = "test.demo.not_null_fact_orders_order_id"
    manifest = {
        "nodes": {
            model_id: {
                "unique_id": model_id,
                "name": "fact_orders",
                "resource_type": "model",
                "original_file_path": "models/fact_orders.sql",
                "compiled_code": "SELECT order_id, amount FROM raw.orders",
                "config": {"materialized": "table"},
                "columns": {
                    "order_id": {"data_type": "INTEGER", "description": "Primary key"},
                    "amount": {"data_type": "NUMBER"},
                },
                "depends_on": {"nodes": ["source.demo.orders"]},
            },
            test_id: {
                "unique_id": test_id,
                "name": "not_null_fact_orders_order_id",
                "resource_type": "test",
                "depends_on": {"nodes": [model_id]},
                "test_metadata": {"name": "not_null", "kwargs": {"column_name": "order_id"}},
            },
        },
        "sources": {
            "source.demo.orders": {
                "unique_id": "source.demo.orders",
                "name": "orders",
                "source_name": "raw",
                "resource_type": "source",
                "relation_name": "raw.orders",
                "columns": {
                    "order_id": {"data_type": "INTEGER"},
                    "amount": {"data_type": "NUMBER"},
                },
            }
        },
        "parent_map": {
            model_id: ["source.demo.orders"],
            test_id: [model_id],
        },
        "child_map": {
            "source.demo.orders": [model_id],
            model_id: [test_id],
        },
    }
    catalog = {
        "nodes": {
            model_id: {
                "columns": {
                    "order_id": {"type": "INTEGER"},
                    "amount": {"type": "NUMBER"},
                }
            }
        }
    }
    run_results = {
        "args": {"which": "build"},
        "results": [
            {"unique_id": model_id, "status": "success"},
            {
                "unique_id": test_id,
                "status": "fail" if failing_test else "pass",
                "message": "fixture failure" if failing_test else None,
                "failures": 1 if failing_test else 0,
            },
        ],
    }
    (target / "manifest.json").write_text(json.dumps(manifest))
    (target / "catalog.json").write_text(json.dumps(catalog))
    (target / "run_results.json").write_text(json.dumps(run_results))
    return project


def test_clean_dbt_review_is_deterministic_and_signed(tmp_path):
    project = _project(tmp_path)
    review = review_dbt_changes(
        project,
        changed_files=["models/fact_orders.sql"],
        dialect="snowflake",
    )
    assert review["status"] == "PASS"
    assert review["verdict"] == "APPROVE"
    assert review["blockers"] == []
    assert len(review["signature"]) == 64
    assert review["deterministic"] is True
    assert review["llm_blocking_decision"] is False

    impact = change_impact(review)
    assert impact["changed_models"][0]["name"] == "fact_orders"
    assert recommended_tests(review)["review_signature"] == review["signature"]
    assert deployment_risk(review)["risk"] == "LOW"


def test_failed_dbt_test_requests_changes(tmp_path):
    project = _project(tmp_path, failing_test=True)
    review = review_dbt_changes(
        project,
        changed_files=["models/fact_orders.sql"],
    )
    assert review["verdict"] == "REQUEST_CHANGES"
    assert any(item["type"] == "dbt_test" for item in review["blockers"])
    assert deployment_risk(review)["risk"] == "HIGH"


def test_unresolved_changed_model_requests_changes(tmp_path):
    project = _project(tmp_path)
    review = review_dbt_changes(
        project,
        changed_files=["models/not_in_manifest.sql"],
    )
    assert review["verdict"] == "REQUEST_CHANGES"
    assert review["evidence"]["unresolved_files"] == ["models/not_in_manifest.sql"]


def test_github_and_gitlab_delivery_are_external_or_dry_run(monkeypatch, tmp_path):
    review = review_dbt_changes(
        _project(tmp_path),
        changed_files=["models/fact_orders.sql"],
    )

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    skipped = deliver_github_review(
        review,
        repository="acme/demo",
        pull_number=7,
    )
    assert skipped["status"] == "SKIP_EXTERNAL"

    dry = deliver_gitlab_review(
        review,
        project="acme/demo",
        merge_request_iid=9,
        dry_run=True,
    )
    assert dry["status"] == "DRY_RUN"
    assert "body" in dry["payload"]


def test_delivery_uses_injected_transport_and_never_exposes_token(monkeypatch, tmp_path):
    review = review_dbt_changes(
        _project(tmp_path),
        changed_files=["models/fact_orders.sql"],
    )
    monkeypatch.setenv("GITHUB_TOKEN", "top-secret")
    calls = []

    def sender(method, url, headers, payload):
        calls.append((method, url, headers, payload))
        return {"http_status": 200, "body": {"id": 123}}

    result = deliver_github_review(
        review,
        repository="acme/demo",
        pull_number=3,
        sender=sender,
    )
    assert result["status"] == "PASS"
    assert calls[0][0] == "POST"
    assert calls[0][3]["event"] == "APPROVE"
    assert "top-secret" not in json.dumps(result)
