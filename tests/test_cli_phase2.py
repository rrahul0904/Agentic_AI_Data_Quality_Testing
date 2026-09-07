from __future__ import annotations

import json

from agentic_data_platform.cli import DOMAIN_CLI_TOOLS, build_parser, main


def test_cli_exposes_complete_phase2_domain_hierarchy():
    expected = {
        "sql", "lineage", "schema", "warehouse", "diff", "quality", "dbt-run",
        "connection", "metadata", "data-diff", "finops", "governance",
        "provider", "mcp", "skill", "training", "session", "memory", "trace", "job",
    }
    assert expected.issubset(DOMAIN_CLI_TOOLS)

    parser = build_parser()
    args = parser.parse_args(["sql", "classify", "--args", '{"sql":"SELECT 1"}'])
    assert args.command == "sql"
    assert args.operation == "classify"


def test_cli_domain_invokes_tool_registry(capsys):
    result = main(["sql", "classify", "--args", '{"sql":"SELECT 1"}'])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["query_type"] == "read"
    assert payload["blocked"] is False


def test_cli_mutation_requires_builder(capsys, tmp_path):
    args = json.dumps({
        "project": str(tmp_path),
        "content": "remember this",
    })
    result = main(["memory", "save", "--args", args])
    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ERROR"

    result = main(["memory", "save", "--builder", "--args", args])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["memory_id"]


def test_cli_dbt_runtime_has_governed_mutation_split():
    assert DOMAIN_CLI_TOOLS["dbt-run"]["compile"] == "dbt_compile"
    assert DOMAIN_CLI_TOOLS["dbt-run"]["build"] == "dbt_build"
