from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.ide import IDEBridge


def test_ide_workspace_bundle_generates_vscode_extension_tasks_and_bridge_config(tmp_path):
    bridge = IDEBridge(tmp_path)
    plan = bridge.plan_workspace(console_url="http://localhost:3000")

    assert plan["status"] == "PASS"
    assert ".ade/ide.json" in plan["files"]
    assert ".vscode/tasks.json" in plan["files"]
    assert ".ade/vscode-extension/package.json" in plan["files"]
    package = json.loads(plan["files"][".ade/vscode-extension/package.json"])
    commands = {item["command"] for item in package["contributes"]["commands"]}
    assert commands == {
        "ade.openConsole",
        "ade.listSessions",
        "ade.reviewCheckpoint",
        "ade.showCurrentContext",
        "ade.planSelectedEdit",
        "ade.startHostedRunner",
        "ade.startAutomationWorker",
    }
    assert plan["api_url"] == "http://localhost:8000"
    assert {
        "sessions",
        "checkpoint_review",
        "file_context",
        "selected_edit_plan",
        "hosted_runner",
        "automations",
    } <= set(plan["capabilities"])
    assert "approval and execution remain" in plan["files"][".ade/vscode-extension/README.md"]
    assert "${workspaceFolder}" in plan["files"][".vscode/settings.json"]

    result = bridge.apply_workspace(
        plan,
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert result["status"] == "PASS"
    assert result["verified"] is True
    assert (tmp_path / ".ade/vscode-extension/extension.js").is_file()


def test_ide_workspace_apply_recomputes_fingerprint_and_blocks_late_tampering(tmp_path):
    bridge = IDEBridge(tmp_path)
    plan = bridge.plan_workspace()
    approval = plan["approval_fingerprint"]
    plan["files"][".ade/vscode-extension/extension.js"] += "\n// late rewrite\n"

    result = bridge.apply_workspace(plan, approval_fingerprint=approval)

    assert result["status"] == "BLOCKED_APPROVAL"
    assert not (tmp_path / ".ade/vscode-extension/extension.js").exists()


def test_ide_context_and_open_target_are_project_scoped(tmp_path):
    source = tmp_path / "src" / "model.py"
    source.parent.mkdir()
    source.write_text("one\ntwo\nthree\nfour\nfive\n")
    bridge = IDEBridge(tmp_path)

    context = bridge.context("src/model.py", line=3, radius=1)
    assert [item["text"] for item in context["lines"]] == ["two", "three", "four"]
    assert len(context["fingerprint"]) == 64

    opened = bridge.open_target("src/model.py", line=3, column=2)
    assert opened["vscode_uri"].startswith("vscode://file/")
    assert opened["vscode_uri"].endswith(":3:2")

    with pytest.raises(ValueError, match="project-relative"):
        bridge.context("../secret.txt")


def test_ide_edit_is_hash_bound_and_rejects_stale_approval(tmp_path):
    source = tmp_path / "config.txt"
    source.write_text("alpha\nbeta\ngamma\n")
    bridge = IDEBridge(tmp_path)
    replacements = [{"start_line": 2, "end_line": 2, "text": "BETA"}]
    plan = bridge.plan_edit("config.txt", replacements)

    blocked = bridge.apply_edit(
        "config.txt",
        replacements,
        approval_fingerprint="wrong",
    )
    assert blocked["status"] == "BLOCKED_APPROVAL"

    applied = bridge.apply_edit(
        "config.txt",
        replacements,
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert applied["status"] == "PASS"
    assert source.read_text() == "alpha\nBETA\ngamma\n"

    stale_plan = bridge.plan_edit(
        "config.txt",
        [{"start_line": 1, "text": "ALPHA"}],
    )
    source.write_text("changed\nBETA\ngamma\n")
    stale = bridge.apply_edit(
        "config.txt",
        [{"start_line": 1, "text": "ALPHA"}],
        approval_fingerprint=stale_plan["approval_fingerprint"],
    )
    assert stale["status"] == "BLOCKED_APPROVAL"


def test_ide_dev_server_registry(tmp_path):
    bridge = IDEBridge(tmp_path)
    registered = bridge.register_server(
        name="operator-console",
        url="http://localhost:3000",
        pid=123,
        metadata={"kind": "nextjs"},
    )
    assert registered["url"] == "http://localhost:3000"

    listed = bridge.list_servers()
    assert listed["servers"]["operator-console"]["pid"] == 123

    removed = bridge.remove_server("operator-console")
    assert removed["removed"] is True
    assert bridge.list_servers()["servers"] == {}


def test_ide_surfaces_exposed():
    assert set(DOMAIN_CLI_TOOLS["ide"]) == {
        "workspace-plan", "workspace-apply", "context", "open",
        "edit-plan", "edit-apply", "server-register", "servers", "server-remove",
    }
    client = TestClient(create_app())
    assert set(client.get("/api/v1/domains").json()["ide"]) == set(DOMAIN_CLI_TOOLS["ide"])
