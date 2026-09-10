from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.browser import AgentBrowser, plan_browser_actions
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS


def test_browser_plan_validates_urls_refs_and_interactivity():
    plan = plan_browser_actions([
        {"action": "open", "url": "https://example.com"},
        {"action": "snapshot"},
        {"action": "get-title"},
    ])
    assert plan.interactive is False

    interactive = plan_browser_actions([
        {"action": "click", "ref": "@e3"},
        {"action": "fill", "ref": "@e4", "text": "hello"},
    ])
    assert interactive.interactive is True

    with pytest.raises(ValueError, match="http"):
        plan_browser_actions([{"action": "open", "url": "file:///etc/passwd"}])
    with pytest.raises(ValueError, match="@e1"):
        plan_browser_actions([{"action": "click", "ref": "#submit"}])


def test_browser_read_actions_execute_typed_commands_with_injected_executor():
    commands = []

    def execute(command):
        commands.append(command)
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    result = AgentBrowser(execute).execute([
        {"action": "open", "url": "https://example.com"},
        {"action": "snapshot", "cursor": True},
        {"action": "get-url"},
        {"action": "wait", "load": "networkidle"},
        {"action": "screenshot", "path": "artifacts/page.png", "full": True},
    ], session="test")

    assert result["status"] == "PASS"
    assert commands[0] == ["agent-browser", "--session", "test", "open", "https://example.com"]
    assert commands[1][-2:] == ["-i", "-C"]
    assert commands[-1][-2:] == ["--full", "artifacts/page.png"]


def test_browser_interactive_actions_are_blocked_without_explicit_permission():
    calls = []
    browser = AgentBrowser(lambda command: calls.append(command) or {"returncode": 0})

    blocked = browser.execute(
        [{"action": "click", "ref": "@e1"}],
        allow_interactive=False,
    )
    assert blocked["status"] == "BLOCKED_APPROVAL"
    assert calls == []

    passed = browser.execute(
        [{"action": "click", "ref": "@e1"}],
        allow_interactive=True,
    )
    assert passed["status"] == "PASS"
    assert calls[0][-2:] == ["click", "@e1"]


def test_browser_screenshot_cannot_escape_project_relative_output():
    browser = AgentBrowser(lambda _: {"returncode": 0})
    with pytest.raises(ValueError, match="project-relative"):
        browser.execute([{"action": "screenshot", "path": "../secret.png"}])


def test_browser_surfaces_exposed():
    assert DOMAIN_CLI_TOOLS["browser"] == {
        "plan": "browser_plan", "read": "browser_read", "act": "browser_act"
    }
    client = TestClient(create_app())
    assert set(client.get("/api/v1/domains").json()["browser"]) == {"plan", "read", "act"}
