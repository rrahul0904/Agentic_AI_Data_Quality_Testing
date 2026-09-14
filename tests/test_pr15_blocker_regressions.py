from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

from agentic_data_platform.api.competitive import _delete_document_manifest
from agentic_data_platform.remote_workspace import RemoteWorkspaceConfig, SSHRemoteWorkspace
from agentic_data_platform.retrieval import ADESearchIndex


def test_remote_command_requires_approval_even_when_marked_read_only():
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    workspace = SSHRemoteWorkspace(
        RemoteWorkspaceConfig(host="example.internal", user="ade", root="/srv/project"),
        runner=fake_run,
    )

    result = workspace.run(["rm", "-rf", "models"], read_only=True, approved=False)

    assert result["status"] == "APPROVAL_REQUIRED"
    assert result["read_only_requested"] is True
    assert commands == []


def test_remote_filesystem_commands_canonicalize_before_access():
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="safe.sql\n", stderr="")

    workspace = SSHRemoteWorkspace(
        RemoteWorkspaceConfig(host="example.internal", user="ade", root="/srv/project"),
        runner=fake_run,
    )

    result = workspace.read_text("models/safe.sql")

    assert result["status"] == "PASS"
    script = commands[-1][-1]
    assert "realpath -m" in script
    assert 'case "$resolved_target"' in script
    assert '"$resolved_root"/*' in script


def test_search_source_delete_invalidates_document_manifest(tmp_path):
    index = ADESearchIndex(tmp_path / "search.db", index_name="documents")
    with sqlite3.connect(index.database) as connection:
        connection.execute(
            """
            CREATE TABLE ade_document_manifest (
                index_name TEXT NOT NULL,
                source TEXT NOT NULL,
                sync_hash TEXT NOT NULL,
                chunk_ids_json TEXT NOT NULL,
                PRIMARY KEY(index_name, source)
            )
            """
        )
        connection.execute(
            "INSERT INTO ade_document_manifest VALUES (?, ?, ?, ?)",
            ("documents", "invoice.txt", "same-hash", "[]"),
        )

    _delete_document_manifest(index, "invoice.txt")

    with sqlite3.connect(index.database) as connection:
        row = connection.execute(
            "SELECT 1 FROM ade_document_manifest WHERE index_name=? AND source=?",
            ("documents", "invoice.txt"),
        ).fetchone()
    assert row is None


def test_desktop_renderer_uses_runtime_api_url():
    root = Path(__file__).resolve().parents[1]
    renderer = (root / "apps" / "desktop" / "renderer.js").read_text(encoding="utf-8")
    shell = (root / "apps" / "desktop" / "index.html").read_text(encoding="utf-8")

    assert "const API = 'http://127.0.0.1:8001'" not in renderer
    assert "API = state.apiUrl" in renderer
    assert "connect-src http: https:" in shell
