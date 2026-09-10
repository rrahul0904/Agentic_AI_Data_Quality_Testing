from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.ai import AIWorkflowCompiler, SnowflakeAIWorkflowRunner
from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector


def test_ai_workflow_compiles_complete_classify_filter_and_token_steps():
    workflow = {
        "name": "review_enrichment",
        "source_sql": "SELECT review, property_name FROM HOTEL.RAW.REVIEWS",
        "steps": [
            {
                "operation": "filter",
                "input": "review",
                "prompt": "Is this guest review actionable? {0}",
            },
            {
                "operation": "classify",
                "input": "review",
                "categories": ["service", "room", {"label": "food", "description": "Dining feedback"}],
                "alias": "topic",
            },
            {
                "operation": "count-tokens",
                "function_name": "ai_complete",
                "model": "llama3.3-70b",
                "input": "review",
                "alias": "input_tokens",
            },
            {
                "operation": "complete",
                "model": "llama3.3-70b",
                "input": "review",
                "model_parameters": {"temperature": 0},
                "response_format": {"type": "json", "schema": {"type": "object"}},
                "show_details": True,
                "alias": "response",
            },
        ],
    }

    compiled = AIWorkflowCompiler().compile(workflow)
    sql = compiled.sql

    assert compiled.name == "review_enrichment"
    assert compiled.public()["step_count"] == 4
    assert "AI_FILTER(PROMPT(" in sql
    assert "AI_CLASSIFY(review, ARRAY_CONSTRUCT(" in sql
    assert "AI_COUNT_TOKENS('ai_complete', 'llama3.3-70b', review)" in sql
    assert "AI_COMPLETE('llama3.3-70b', review" in sql
    assert "SELECT * FROM step_4" in sql


def test_ai_workflow_compiles_aggregate_and_summarize_with_grouping():
    agg = AIWorkflowCompiler().compile({
        "name": "review_themes",
        "source_sql": "SELECT property_name, review FROM HOTEL.RAW.REVIEWS",
        "steps": [
            {
                "operation": "agg",
                "input": "review",
                "instruction": "Describe the top guest complaints.",
                "group_by": ["property_name"],
                "alias": "themes",
            }
        ],
    })
    assert "AI_AGG(review, 'Describe the top guest complaints.')" in agg.sql
    assert "GROUP BY property_name" in agg.sql

    summary = AIWorkflowCompiler().compile({
        "name": "review_summary",
        "source_sql": "SELECT review FROM HOTEL.RAW.REVIEWS",
        "steps": [
            {
                "operation": "summarize-agg",
                "input": "review",
                "alias": "summary",
            }
        ],
    })
    assert "AI_SUMMARIZE_AGG(review) AS summary" in summary.sql


def test_ai_workflow_rejects_mutating_source_and_expression_subquery():
    compiler = AIWorkflowCompiler()
    with pytest.raises(ValueError, match="read-only"):
        compiler.compile({
            "name": "bad",
            "source_sql": "DELETE FROM HOTEL.RAW.REVIEWS",
            "steps": [{"operation": "filter", "input": "review"}],
        })

    with pytest.raises(ValueError, match="subqueries"):
        compiler.compile({
            "name": "bad_expr",
            "source_sql": "SELECT review FROM HOTEL.RAW.REVIEWS",
            "steps": [
                {
                    "operation": "complete",
                    "model": "llama3.3-70b",
                    "input": "(SELECT secret FROM HOTEL.ADMIN.SECRETS LIMIT 1)",
                }
            ],
        })


def test_ai_workflow_runner_executes_compiled_read_only_sql():
    captured = []

    def execute(sql):
        captured.append(sql)
        return {
            "columns": ("PROPERTY_NAME", "SUMMARY"),
            "rows": (
                {"PROPERTY_NAME": "Boston", "SUMMARY": "Mostly service complaints."},
            ),
            "query_id": "q-ai-1",
        }

    connector = SnowflakeConnector(execute, SnowflakeConfig(database="HOTEL", schema="RAW"))
    workflow = {
        "name": "review_summary",
        "source_sql": "SELECT property_name, review FROM HOTEL.RAW.REVIEWS",
        "steps": [
            {
                "operation": "agg",
                "input": "review",
                "instruction": "Summarize guest complaints.",
                "group_by": ["property_name"],
                "alias": "summary",
            }
        ],
    }

    result = SnowflakeAIWorkflowRunner(connector).run(workflow)

    assert result["status"] == "PASS"
    assert result["query_id"] == "q-ai-1"
    assert result["row_count"] == 1
    assert "AI_AGG" in captured[0]


def test_ai_workflow_surfaces_exposed():
    assert DOMAIN_CLI_TOOLS["ai-workflow"] == {
        "plan": "ai_workflow_plan",
        "run": "ai_workflow_run",
    }
    client = TestClient(create_app())
    assert set(client.get("/api/v1/domains").json()["ai-workflow"]) == {"plan", "run"}

    response = client.post(
        "/api/v1/ai-workflow/plan",
        json={
            "args": {
                "workflow": {
                    "name": "simple",
                    "source_sql": "SELECT review FROM HOTEL.RAW.REVIEWS",
                    "steps": [
                        {
                            "operation": "complete",
                            "model": "llama3.3-70b",
                            "input": "review",
                            "alias": "answer",
                        }
                    ],
                }
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PASS"
