from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.rules import RuleStore
from agentic_data_platform.session import SessionRuntime, SessionStore, load_instructions
from agentic_data_platform.tools.builtin import build_tool_registry


def test_rule_precedence_is_global_then_project_then_more_specific(tmp_path):
    project = tmp_path / "project"
    global_root = tmp_path / "global"
    project.mkdir()
    global_root.mkdir()

    store = RuleStore(project, global_root=global_root)
    store.save(
        "global-default",
        "Use deterministic evidence.",
        scope="global",
        priority=1,
    )
    store.save(
        "project-default",
        "Prefer project conventions.",
        scope="project",
        priority=1,
    )
    store.save(
        "python-specific",
        "Run Python tests after edits.",
        scope="project",
        priority=5,
        apply_paths=["src/**/*.py"],
    )

    resolved = store.resolve(target_path="src/pkg/module.py")
    names = [item["name"] for item in resolved["rules"]]

    assert names == ["global-default", "project-default", "python-specific"]
    assert resolved["resolution_fingerprint"]
    assert resolved["policy_effect"] == "instructions_only_tool_policy_remains_authoritative"


def test_path_scoped_rule_is_not_applied_outside_target(tmp_path):
    store = RuleStore(tmp_path, global_root=tmp_path / "global")
    store.save(
        "sql-rule",
        "Use read-only SQL during diagnosis.",
        apply_paths=["models/**/*.sql"],
    )

    python = store.resolve(target_path="src/app.py")
    sql = store.resolve(target_path="models/marts/revenue.sql")

    assert "sql-rule" not in {item["name"] for item in python["rules"]}
    assert "sql-rule" in {item["name"] for item in sql["rules"]}


def test_static_instruction_files_are_resolved_and_fingerprinted(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Always verify evidence.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Keep changes scoped.\n", encoding="utf-8")

    store = RuleStore(tmp_path, global_root=tmp_path / "global")
    resolved = store.resolve()

    names = {item["name"] for item in resolved["rules"]}
    assert "static:AGENTS.md" in names
    assert "static:CLAUDE.md" in names
    assert all(item["rule_fingerprint"] for item in resolved["rules"])


def test_rule_enable_disable_and_remove_are_explicit(tmp_path):
    store = RuleStore(tmp_path, global_root=tmp_path / "global")
    saved = store.save("toggle", "Use tests.", enabled=True)
    assert saved["enabled"] is True

    disabled = store.set_enabled("toggle", False)
    assert disabled["enabled"] is False
    assert "toggle" not in {item["name"] for item in store.resolve()["rules"]}

    enabled = store.set_enabled("toggle", True)
    assert enabled["enabled"] is True
    assert "toggle" in {item["name"] for item in store.resolve()["rules"]}

    removed = store.remove("toggle")
    assert removed["removed"] is True


def test_rule_apply_paths_cannot_escape_workspace(tmp_path):
    store = RuleStore(tmp_path, global_root=tmp_path / "global")
    try:
        store.save("escape", "bad", apply_paths=["../secrets/*"])
    except ValueError as exc:
        assert "workspace-relative" in str(exc)
    else:
        raise AssertionError("escaping rule path should be rejected")


def test_load_instructions_and_session_prompt_use_same_rule_hierarchy(tmp_path):
    global_root = tmp_path / "global"
    project = tmp_path / "project"
    global_root.mkdir()
    project.mkdir()

    store = RuleStore(project, global_root=global_root)
    store.save("global-rule", "Global evidence rule.", scope="global")
    store.save("project-rule", "Project lineage rule.", scope="project")

    instructions = load_instructions(project, global_root=global_root)
    assert [item["name"] for item in instructions] == ["global-rule", "project-rule"]

    # SessionRuntime reads the same hierarchy through ADE_GLOBAL_RULES_ROOT.
    import os
    original = os.environ.get("ADE_GLOBAL_RULES_ROOT")
    os.environ["ADE_GLOBAL_RULES_ROOT"] = str(global_root)
    try:
        session_store = SessionStore(tmp_path / "sessions.db")
        runtime = SessionRuntime(session_store)
        session_id = runtime.create()["session_id"]
        runtime.append(session_id, "user", "inspect")
        prompt = runtime.prompt(session_id, project_root=project)
    finally:
        if original is None:
            os.environ.pop("ADE_GLOBAL_RULES_ROOT", None)
        else:
            os.environ["ADE_GLOBAL_RULES_ROOT"] = original

    system = prompt["messages"][0]["content"]
    assert "Global evidence rule." in system
    assert "Project lineage rule." in system


def test_rules_tools_and_api_are_exposed():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "rule_list",
        "rule_resolve",
        "rule_show",
        "rule_save",
        "rule_enable",
        "rule_remove",
    } <= names

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    rules = response.json()["rules"]
    assert set(rules) == {"list", "resolve", "show", "save", "enable", "remove"}
