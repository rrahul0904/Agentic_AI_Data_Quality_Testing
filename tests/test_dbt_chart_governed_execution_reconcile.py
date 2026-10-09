from __future__ import annotations

from agentic_data_platform.dbt.nextgen import chart_query_contract


def test_governed_chart_contract_remains_exact_and_read_only() -> None:
    spec = {
        "dashboard": {
            "name": "reconciliation_dashboard",
            "charts": [
                {
                    "name": "revenue_total",
                    "type": "number",
                    "sql": "select 42 as revenue",
                }
            ],
        }
    }

    first = chart_query_contract({"spec": spec})
    second = chart_query_contract({"spec": spec})

    assert first["status"] == "READY"
    assert first["query_source"] == "explicit-read-only-sql"
    assert first["sql"] == "select 42 as revenue"
    assert first["fingerprint"] == second["fingerprint"]
    assert "synth" not in first["query_source"]


def test_metric_only_chart_fails_closed_without_governed_query() -> None:
    contract = chart_query_contract(
        {
            "spec": {
                "dashboard": {
                    "name": "governed_only",
                    "charts": [
                        {
                            "name": "revenue",
                            "metric": "revenue",
                        }
                    ],
                }
            }
        }
    )

    assert contract["status"] == "NEEDS_VERIFIED_QUERY"
    assert contract["sql"] is None
    assert "will not synthesize SQL" in contract["reason"]


def test_mutating_chart_sql_is_rejected_before_execution_contract() -> None:
    contract = chart_query_contract(
        {
            "spec": {
                "dashboard": {
                    "name": "blocked_dashboard",
                    "charts": [
                        {
                            "name": "unsafe",
                            "sql": "delete from production.orders",
                        }
                    ],
                }
            }
        }
    )

    assert contract["status"] == "FAIL"
    assert any("read-only" in error for error in contract["errors"])
