from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.workspace_files import (
    workspace_file_apply,
    workspace_file_diff,
    workspace_file_find,
    workspace_file_glob,
    workspace_file_grep,
    workspace_file_plan,
    workspace_file_read,
    workspace_file_undo,
)


def _apply(tmp_path, operation, path, **kwargs):
    plan = workspace_file_plan(tmp_path, operation, path, **kwargs)
    assert plan["status"] == "PASS"
    result = workspace_file_apply(
        tmp_path,
        operation,
        path,
        approval_fingerprint=plan["approval_fingerprint"],
        **kwargs,
    )
    assert result["status"] == "PASS"
    return plan, result


def test_workspace_read_glob_find_grep_and_diff_are_fingerprinted(tmp_path):
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "app.py"
    target.write_text("alpha\nneedle here\nomega\n", encoding="utf-8")

    read = workspace_file_read(tmp_path, "src/app.py")
    assert read["status"] == "PASS"
    assert read["sha256"]
    assert read["truncated"] is False

    listing = workspace_file_glob(tmp_path, "**/*.py")
    assert [item["path"] for item in listing["files"]] == ["src/app.py"]
    assert listing["listing_fingerprint"]

    found = workspace_file_find(tmp_path, "app")
    assert found["matches"][0]["path"] == "src/app.py"

    grep = workspace_file_grep(tmp_path, "needle")
    assert grep["matches"][0]["line"] == 2
    assert grep["matches"][0]["file_sha256"] == read["sha256"]

    diff = workspace_file_diff(
        tmp_path,
        "src/app.py",
        proposed_content="alpha\nchanged\nomega\n",
    )
    assert diff["changed"] is True
    assert "@@" in diff["diff"]
    assert diff["source_hash"] == read["sha256"]


def test_workspace_create_write_patch_delete_and_undo(tmp_path):
    create_plan, _ = _apply(tmp_path, "create", "notes.txt", content="one\ntwo\n")
    assert (tmp_path / "notes.txt").read_text() == "one\ntwo\n"
    assert workspace_file_undo(tmp_path, create_plan["approval_fingerprint"])["status"] == "PASS"
    assert not (tmp_path / "notes.txt").exists()

    (tmp_path / "notes.txt").write_text("one\ntwo\n", encoding="utf-8")
    write_plan, _ = _apply(tmp_path, "write", "notes.txt", content="ONE\ntwo\n")
    assert (tmp_path / "notes.txt").read_text() == "ONE\ntwo\n"
    workspace_file_undo(tmp_path, write_plan["approval_fingerprint"])
    assert (tmp_path / "notes.txt").read_text() == "one\ntwo\n"

    patch_plan, _ = _apply(
        tmp_path,
        "patch",
        "notes.txt",
        old_text="two",
        new_text="TWO",
    )
    assert (tmp_path / "notes.txt").read_text() == "one\nTWO\n"
    workspace_file_undo(tmp_path, patch_plan["approval_fingerprint"])
    assert (tmp_path / "notes.txt").read_text() == "one\ntwo\n"

    delete_plan, _ = _apply(tmp_path, "delete", "notes.txt")
    assert not (tmp_path / "notes.txt").exists()
    workspace_file_undo(tmp_path, delete_plan["approval_fingerprint"])
    assert (tmp_path / "notes.txt").read_text() == "one\ntwo\n"


def test_workspace_move_and_undo_restores_source(tmp_path):
    (tmp_path / "old.txt").write_text("payload\n", encoding="utf-8")
    plan, result = _apply(tmp_path, "move", "old.txt", destination="nested/new.txt")

    assert result["result_hash"] == plan["source_hash"]
    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "nested" / "new.txt").read_text() == "payload\n"

    undone = workspace_file_undo(tmp_path, plan["approval_fingerprint"])
    assert undone["status"] == "PASS"
    assert (tmp_path / "old.txt").read_text() == "payload\n"
    assert not (tmp_path / "nested" / "new.txt").exists()


def test_workspace_mutation_rejects_stale_source_and_tampered_approval(tmp_path):
    target = tmp_path / "state.txt"
    target.write_text("before\n", encoding="utf-8")
    read = workspace_file_read(tmp_path, "state.txt")
    plan = workspace_file_plan(
        tmp_path,
        "write",
        "state.txt",
        content="after\n",
        expected_source_hash=read["sha256"],
    )
    assert plan["status"] == "PASS"

    stale = workspace_file_apply(
        tmp_path,
        "write",
        "state.txt",
        content="after\n",
        approval_fingerprint="tampered",
        expected_source_hash=read["sha256"],
    )
    assert stale["status"] == "STALE_APPROVAL"
    assert target.read_text() == "before\n"

    target.write_text("changed externally\n", encoding="utf-8")
    stale_source = workspace_file_apply(
        tmp_path,
        "write",
        "state.txt",
        content="after\n",
        approval_fingerprint=plan["approval_fingerprint"],
        expected_source_hash=read["sha256"],
    )
    assert stale_source["status"] == "STALE_SOURCE"


def test_workspace_verification_failure_rolls_back(tmp_path):
    target = tmp_path / "verified.txt"
    target.write_text("before\n", encoding="utf-8")
    command = [sys.executable, "-c", "raise SystemExit(7)"]
    plan = workspace_file_plan(
        tmp_path,
        "write",
        "verified.txt",
        content="after\n",
        verification_command=command,
    )
    result = workspace_file_apply(
        tmp_path,
        "write",
        "verified.txt",
        content="after\n",
        verification_command=command,
        approval_fingerprint=plan["approval_fingerprint"],
    )
    assert result["status"] == "VERIFICATION_FAILED_ROLLED_BACK"
    assert target.read_text() == "before\n"


def test_workspace_paths_and_patch_matching_are_strict(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        workspace_file_read(tmp_path, "../outside.txt")

    target = tmp_path / "duplicate.txt"
    target.write_text("same same", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly once"):
        workspace_file_plan(
            tmp_path,
            "patch",
            "duplicate.txt",
            old_text="same",
            new_text="new",
        )


def test_workspace_file_tools_and_api_are_exposed():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    expected = {
        "workspace_file_read",
        "workspace_file_glob",
        "workspace_file_find",
        "workspace_file_grep",
        "workspace_file_diff",
        "workspace_file_plan",
        "workspace_file_apply",
        "workspace_file_undo",
        "workspace_region_edit_plan",
        "workspace_region_edit_apply",
    }
    assert expected <= names

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    advanced = response.json()["advanced"]
    assert {
        "file-read",
        "file-glob",
        "file-find",
        "file-grep",
        "file-diff",
        "file-plan",
        "file-apply",
        "file-undo",
    } <= set(advanced)
