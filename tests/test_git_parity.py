from __future__ import annotations

import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.advanced_capabilities import (
    git_change_apply,
    git_change_plan,
    git_diff,
    git_log,
    git_remotes,
    git_review_evidence,
    git_status,
)
from agentic_data_platform.api.app import create_app
from agentic_data_platform.tools.builtin import build_tool_registry


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def _run(path, *args):
    return subprocess.run(
        ["git", *args],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path):
    repo = tmp_path / "work"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.email", "ade@example.test")
    _run(repo, "config", "user.name", "ADE Tests")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run(repo, "add", "README.md")
    _run(repo, "commit", "-m", "seed")
    _run(repo, "branch", "-M", "main")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    _run(repo, "remote", "add", "origin", str(remote))
    _run(repo, "push", "-u", "origin", "main")
    return repo, remote


def _apply(repo, operation, **kwargs):
    plan = git_change_plan(repo, operation, **kwargs)
    assert plan["status"] == "PASS"
    result = git_change_apply(
        repo,
        operation,
        approval_fingerprint=plan["approval_fingerprint"],
        **kwargs,
    )
    assert result["status"] == "PASS", result
    return plan, result


def test_git_read_surfaces_return_reviewable_evidence(tmp_path):
    repo, _ = _repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    status = git_status(repo)
    diff = git_diff(repo, paths=["README.md"])
    history = git_log(repo)
    remotes = git_remotes(repo)
    review = git_review_evidence(repo)

    assert status["status"] == "PASS"
    assert status["head"]
    assert diff["status"] == "PASS"
    assert "+changed" in diff["stdout"]
    assert diff["diff_fingerprint"]
    assert history["commits"][0]["subject"] == "seed"
    assert remotes["remotes"]
    assert review["status"] == "PASS"
    assert review["evidence_fingerprint"]


def test_git_branch_switch_commit_restore_revert_and_local_push(tmp_path):
    repo, remote = _repo(tmp_path)

    _apply(repo, "branch", branch="feature/parity")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _, committed = _apply(
        repo,
        "commit",
        message="feat: parity",
        paths=["feature.txt"],
        verification_command=[sys.executable, "-c", "print('verified')"],
    )
    feature_commit = committed["head"]
    assert committed["review_evidence"]["changed_files"] == ["feature.txt"]

    _, pushed = _apply(repo, "push", branch="feature/parity", remote="origin")
    assert pushed["force_push"] is False
    remote_head = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/feature/parity"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote_head == feature_commit

    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    _apply(repo, "restore", paths=["README.md"])
    assert (repo / "README.md").read_text() == "seed\n"

    _, reverted = _apply(repo, "revert", commit=feature_commit)
    assert reverted["head"] != feature_commit
    assert not (repo / "feature.txt").exists()

    _apply(repo, "switch", branch="main")
    assert "main" in git_status(repo)["stdout"]


def test_git_fetch_works_against_local_remote(tmp_path):
    repo, _ = _repo(tmp_path)
    _apply(repo, "fetch", remote="origin")


def test_destructive_git_operations_are_blocked_before_execution(tmp_path):
    repo, _ = _repo(tmp_path)
    for operation in ("force_push", "hard_reset", "branch_delete", "history_rewrite", "rebase"):
        plan = git_change_plan(repo, operation)
        assert plan["status"] == "BLOCKED_POLICY"
        assert "disabled" in plan["reason"]


def test_git_tools_and_api_expose_review_surface():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "git_status",
        "git_diff",
        "git_log",
        "git_remotes",
        "git_review_evidence",
        "git_change_plan",
        "git_change_apply",
    } <= names

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    advanced = response.json()["advanced"]
    assert {
        "git-status",
        "git-diff",
        "git-log",
        "git-remotes",
        "git-review-evidence",
        "git-plan",
        "git-apply",
    } <= set(advanced)
