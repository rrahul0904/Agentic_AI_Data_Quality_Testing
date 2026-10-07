from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from agentic_data_platform.projects.sources import ProjectSourceError, materialize_git_project, resolve_hosted_project


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "origin"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "ade@example.invalid")
    _git(repo, "config", "user.name", "ADE Test")
    (repo / "README.md").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "--quiet", "-m", "initial")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("v2\n", encoding="utf-8")
    _git(repo, "commit", "--quiet", "-am", "second")
    return repo, first


def test_filesystem_source_preserves_existing_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = resolve_hosted_project({"ADE_PROJECT_SOURCE_MODE": "filesystem", "ADE_PROJECT_ROOT": str(project)})
    assert result.root == project.resolve()
    assert result.mode == "filesystem"
    assert result.source_ref is None


def test_filesystem_source_fails_closed_for_missing_root(tmp_path: Path) -> None:
    with pytest.raises(ProjectSourceError, match="does not exist"):
        resolve_hosted_project(
            {"ADE_PROJECT_SOURCE_MODE": "filesystem", "ADE_PROJECT_ROOT": str(tmp_path / "missing")}
        )


def test_git_source_materializes_exact_ref_and_writes_receipt(tmp_path: Path) -> None:
    origin, first_commit = _make_repo(tmp_path)
    result = materialize_git_project(
        str(origin), ref=first_commit, workspace_root=tmp_path / "workspaces", allow_local=True
    )
    assert result.mode == "git"
    assert result.source_ref == first_commit
    assert (result.root / "README.md").read_text(encoding="utf-8") == "v1\n"
    assert not (result.root / ".git").exists()
    receipt = json.loads((result.root / ".ade" / "project-source.json").read_text(encoding="utf-8"))
    assert receipt["commit_sha"] == first_commit
    assert receipt["requested_ref"] == first_commit


def test_git_source_reuses_explicit_ref_materialization(tmp_path: Path) -> None:
    origin, first_commit = _make_repo(tmp_path)
    first = materialize_git_project(
        str(origin), ref=first_commit, workspace_root=tmp_path / "workspaces", allow_local=True
    )
    sentinel = first.root / "sentinel.txt"
    sentinel.write_text("reuse", encoding="utf-8")
    second = materialize_git_project(
        str(origin), ref=first_commit, workspace_root=tmp_path / "workspaces", allow_local=True
    )
    assert second.root == first.root
    assert sentinel.read_text(encoding="utf-8") == "reuse"


def test_hosted_git_source_rejects_non_https_url(tmp_path: Path) -> None:
    origin, _ = _make_repo(tmp_path)
    with pytest.raises(ProjectSourceError, match="https://"):
        materialize_git_project(str(origin), workspace_root=tmp_path / "workspaces")


def test_git_source_rejects_symlinked_project_content(tmp_path: Path) -> None:
    origin, _ = _make_repo(tmp_path)
    link = origin / "outside-link"
    link.symlink_to("/etc/passwd")
    _git(origin, "add", "outside-link")
    _git(origin, "commit", "--quiet", "-m", "add symlink")
    ref = _git(origin, "rev-parse", "HEAD")
    with pytest.raises(ProjectSourceError, match="unsupported symlink"):
        materialize_git_project(
            str(origin), ref=ref, workspace_root=tmp_path / "workspaces", allow_local=True
        )
