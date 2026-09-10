from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.notebooks import NotebookAgent
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


def _notebook(tmp_path):
    path = tmp_path / "analysis.ipynb"
    path.write_text(json.dumps({
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {"tags": ["intro"]},
                "source": ["# Reservation analysis\n"],
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {"vscode": {"languageId": "python"}},
                "outputs": [{"output_type": "stream", "name": "stdout", "text": ["ok\n"]}],
                "source": ["print('old')\n"],
            },
        ],
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }))
    return path


def test_notebook_create_plan_apply_and_local_execution_skip(tmp_path, monkeypatch):
    path = tmp_path / "generated" / "analysis.ipynb"
    cells = [
        {"cell_type": "markdown", "source": "# Generated analysis\n"},
        {"cell_type": "code", "source": "value = 40 + 2\nprint(value)\n"},
    ]
    agent = NotebookAgent()

    plan = agent.plan_create(path, cells)
    assert plan["status"] == "PASS"
    assert plan["cell_count"] == 2
    assert plan["kernel"]["name"] == "python3"

    blocked = agent.apply_create(path, cells, approval_fingerprint="wrong")
    assert blocked["status"] == "BLOCKED_APPROVAL"
    assert not path.exists()

    applied = agent.apply_create(
        path,
        cells,
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert applied["status"] == "PASS"
    assert applied["verified"] is True
    created = json.loads(path.read_text())
    assert created["nbformat"] == 4
    assert created["cells"][1]["outputs"] == []
    assert created["cells"][1]["execution_count"] is None

    monkeypatch.setattr("agentic_data_platform.notebooks.agent.shutil.which", lambda _: None)
    local = agent.run_local(path)
    assert local["status"] == "SKIP_EXTERNAL"
    assert local["command"][:4] == ["jupyter", "nbconvert", "--to", "notebook"]


def test_notebook_create_refuses_unapproved_overwrite(tmp_path):
    path = tmp_path / "existing.ipynb"
    path.write_text("{}")
    cells = [{"cell_type": "code", "source": "print('new')\n"}]
    agent = NotebookAgent()
    plan = agent.plan_create(path, cells)

    with pytest.raises(FileExistsError):
        agent.apply_create(
            path,
            cells,
            approval_fingerprint=plan["approval_fingerprint"],
        )


def test_notebook_agent_inspect_plan_apply_and_stale_approval(tmp_path):
    path = _notebook(tmp_path)
    agent = NotebookAgent()

    inspected = agent.inspect(path)
    assert inspected["status"] == "PASS"
    assert inspected["cell_count"] == 2
    assert inspected["cells"][1]["language"] == "python"
    assert inspected["cells"][1]["has_outputs"] is True

    operations = [
        {"action": "replace", "index": 1, "source": "print('new')\n"},
        {"action": "insert", "index": 2, "cell_type": "markdown", "source": "Done\n"},
    ]
    plan = agent.plan_patch(path, operations)
    assert plan["source_fingerprint"] == inspected["fingerprint"]
    assert plan["approval_fingerprint"]

    blocked = agent.apply_patch(path, operations, approval_fingerprint="wrong")
    assert blocked["status"] == "BLOCKED_APPROVAL"
    assert "old" in path.read_text()

    applied = agent.apply_patch(
        path,
        operations,
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert applied["status"] == "PASS"
    assert applied["verified"] is True
    updated = json.loads(path.read_text())
    assert updated["cells"][1]["source"] == ["print('new')\n"]
    assert updated["cells"][2]["cell_type"] == "markdown"


def test_notebook_plan_is_invalidated_if_notebook_changes(tmp_path):
    path = _notebook(tmp_path)
    agent = NotebookAgent()
    operations = [{"action": "replace", "index": 1, "source": "print('approved')\n"}]
    plan = agent.plan_patch(path, operations)

    data = json.loads(path.read_text())
    data["cells"][1]["source"] = ["print('changed elsewhere')\n"]
    path.write_text(json.dumps(data))

    result = agent.apply_patch(
        path,
        operations,
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert result["status"] == "BLOCKED_APPROVAL"


def test_notebook_snowflake_commands_and_offline_skip(tmp_path, monkeypatch):
    assert NotebookAgent.snowflake_command(
        "deploy",
        identifier="HOTEL.AI.RESERVATION_NOTEBOOK",
        project_definition="snowflake.yml",
        connection="dev",
    ) == [
        "snow",
        "notebook",
        "deploy",
        "HOTEL.AI.RESERVATION_NOTEBOOK",
        "--project",
        "snowflake.yml",
        "--connection",
        "dev",
    ]
    monkeypatch.setattr("agentic_data_platform.notebooks.agent.shutil.which", lambda _: None)
    result = NotebookAgent.run_snowflake(
        "execute",
        identifier="HOTEL.AI.RESERVATION_NOTEBOOK",
        cwd=tmp_path,
    )
    assert result["status"] == "SKIP_EXTERNAL"
    assert result["command"][:3] == ["snow", "notebook", "execute"]


def test_notebook_mutation_surface_requires_approval(tmp_path):
    path = _notebook(tmp_path)
    registry = build_tool_registry()
    definition = registry.describe("notebook_patch_apply")
    operations = [{"action": "replace", "index": 1, "source": "print('new')\n"}]
    plan = NotebookAgent().plan_patch(path, operations)
    request = ToolRequest(
        tool="notebook_patch_apply",
        operation="notebook_patch_apply",
        environment=Environment.DEV,
        risk=definition.risk,
        args={
            "path": str(path),
            "operations": operations,
            "approval_fingerprint": plan["approval_fingerprint"],
        },
    )
    with pytest.raises(PermissionError):
        registry.invoke(ToolInvocation(request, run_id="nb", actor_mode=ActorMode.BUILDER))

    result = registry.invoke(
        ToolInvocation(
            request,
            run_id="nb-approved",
            actor_mode=ActorMode.BUILDER,
            approved=True,
        )
    )
    assert result["status"] == "PASS"


def test_notebook_surfaces_exposed():
    assert set(DOMAIN_CLI_TOOLS["notebook"]) == {
        "inspect", "create-plan", "create-apply", "local-run",
        "patch-plan", "patch-apply", "snowflake-plan", "snowflake-run"
    }
    client = TestClient(create_app())
    domains = client.get("/api/v1/domains").json()
    assert set(domains["notebook"]) == set(DOMAIN_CLI_TOOLS["notebook"])
