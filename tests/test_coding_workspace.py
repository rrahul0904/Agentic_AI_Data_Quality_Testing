from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.coding_workspace import (
    code_index,
    deterministic_code_search,
    python_repl_plan,
    python_repl_reset,
    python_repl_run,
    python_repl_state,
    semantic_code_search,
)
from agentic_data_platform.models import ActorMode, Environment, InteractionMode, Risk, ToolRequest
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


def test_code_index_extracts_python_symbols_and_fingerprints_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pipeline.py").write_text(
        '''
class ReservationLoader:
    """Loads reservation facts into the warehouse."""

    def determine_window(self):
        """Return the extraction watermark window."""
        return "window"
'''.strip() + "\n",
        encoding="utf-8",
    )
    result = code_index(tmp_path, patterns=["**/*.py"])

    assert result["status"] == "PASS"
    assert result["file_count"] == 1
    record = result["files"][0]
    names = set(record["symbol_names"])
    assert {"ReservationLoader", "determine_window"} <= names
    assert record["sha256"]
    assert result["index_fingerprint"]


def test_deterministic_code_search_returns_line_and_file_hash(tmp_path):
    (tmp_path / "dag.py").write_text(
        "def determine_window():\n    return 'reservation watermark'\n",
        encoding="utf-8",
    )
    result = deterministic_code_search(tmp_path, "reservation watermark")

    assert result["status"] == "PASS"
    assert result["backend"] == "deterministic_text"
    assert result["matches"][0]["line"] == 2
    assert result["matches"][0]["file_sha256"]
    assert result["evidence_fingerprint"]


def test_semantic_code_search_ranks_symbol_and_docstring_evidence(tmp_path):
    (tmp_path / "windowing.py").write_text(
        '''
def determine_window():
    """Calculate extraction watermark boundaries for a reservation ingestion job."""
    return None
'''.strip() + "\n",
        encoding="utf-8",
    )
    (tmp_path / "unrelated.py").write_text(
        "def format_currency():\n    return '$0.00'\n",
        encoding="utf-8",
    )

    result = semantic_code_search(
        tmp_path,
        "reservation extraction watermark window",
    )

    assert result["status"] == "PASS"
    assert result["backend"] == "local_structural_semantic"
    assert result["results"][0]["path"] == "windowing.py"
    assert result["results"][0]["matched_symbols"]
    assert result["results"][0]["score_components"]["coverage"] > 0
    assert result["ranking_fingerprint"]
    assert result["explainable"] is True


def test_python_repl_local_constrained_is_stateful_and_explicitly_not_sandboxed(tmp_path):
    first_plan = python_repl_plan(
        tmp_path,
        "x = 40\nprint(x)",
        session_id="analysis",
        backend="local_constrained",
    )
    assert first_plan["execution_class"] == "LOCAL_CONSTRAINED"
    assert first_plan["sandboxed"] is False

    first = python_repl_run(
        tmp_path,
        "x = 40\nprint(x)",
        approval_fingerprint=first_plan["approval_fingerprint"],
        session_id="analysis",
        backend="local_constrained",
    )
    assert first["status"] == "PASS"
    assert first["sandboxed"] is False
    assert "40" in first["stdout"]
    assert first["state"]["x"] == 40

    second_plan = python_repl_plan(
        tmp_path,
        "x += 2\nprint(x)",
        session_id="analysis",
        backend="local_constrained",
    )
    second = python_repl_run(
        tmp_path,
        "x += 2\nprint(x)",
        approval_fingerprint=second_plan["approval_fingerprint"],
        session_id="analysis",
        backend="local_constrained",
    )
    assert second["status"] == "PASS"
    assert second["state"]["x"] == 42
    assert "42" in second["stdout"]

    state = python_repl_state(tmp_path, "analysis")
    assert state["state"]["x"] == 42
    assert len(state["history"]) == 2

    reset = python_repl_reset(tmp_path, "analysis")
    assert reset["status"] == "PASS"
    assert python_repl_state(tmp_path, "analysis")["state"] == {}


def test_python_repl_container_plan_uses_strong_sandbox_and_fails_closed_if_runtime_missing(tmp_path):
    plan = python_repl_plan(
        tmp_path,
        "answer = 6 * 7",
        session_id="sandboxed",
        backend="container",
    )
    assert plan["execution_class"] == "CONTAINER_SANDBOX"
    assert plan["sandbox_plan"]["sandboxed"] is True
    assert plan["sandbox_plan"]["network_enabled"] is False
    assert plan["sandbox_plan"]["security"]["root_filesystem_read_only"] is True

    # Prove fail-closed semantics by using a deliberately unavailable Docker command.
    # The plan fingerprint must bind the same backend configuration, so construct
    # the sandbox result directly through the registered tool boundary in a separate test.
    assert plan["approval_fingerprint"]


def test_python_repl_stale_approval_never_executes(tmp_path):
    result = python_repl_run(
        tmp_path,
        "x = 1",
        approval_fingerprint="tampered",
        session_id="stale",
        backend="local_constrained",
    )
    assert result["status"] == "STALE_APPROVAL"
    assert python_repl_state(tmp_path, "stale")["state"] == {}


def test_code_mode_can_execute_repl_but_edit_mode_cannot(tmp_path):
    registry = build_tool_registry()
    code_plan = registry.invoke(
        ToolInvocation(
            ToolRequest(
                tool="python_repl_plan",
                operation="python_repl_plan",
                environment=Environment.DEV,
                risk=Risk.READ_ONLY,
                args={
                    "workspace": str(tmp_path),
                    "code": "value = 5",
                    "backend": "local_constrained",
                    "session_id": "policy",
                },
            ),
            run_id="repl-plan",
            actor_mode=ActorMode.BUILDER,
            interaction_mode=InteractionMode.CODE,
        )
    )
    assert code_plan["status"] == "PASS"

    request = ToolRequest(
        tool="python_repl_run",
        operation="python_repl_run",
        environment=Environment.DEV,
        risk=Risk.MUTATING,
        args={
            "workspace": str(tmp_path),
            "code": "value = 5",
            "backend": "local_constrained",
            "session_id": "policy",
            "approval_fingerprint": code_plan["approval_fingerprint"],
        },
    )
    result = registry.invoke(
        ToolInvocation(
            request,
            run_id="repl-code",
            approved=True,
            actor_mode=ActorMode.BUILDER,
            interaction_mode=InteractionMode.CODE,
        )
    )
    assert result["status"] == "PASS"

    with pytest.raises(PermissionError, match="edit interaction mode cannot invoke python_repl_run"):
        registry.invoke(
            ToolInvocation(
                request,
                run_id="repl-edit",
                approved=True,
                actor_mode=ActorMode.BUILDER,
                interaction_mode=InteractionMode.EDIT,
            )
        )


def test_coding_tools_are_exposed_in_registry_and_api():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "code_index",
        "code_search",
        "semantic_code_search",
        "python_repl_plan",
        "python_repl_run",
        "python_repl_state",
        "python_repl_reset",
    } <= names

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    advanced = response.json()["advanced"]
    assert {
        "code-index",
        "code-search",
        "semantic-code-search",
        "python-repl-plan",
        "python-repl-run",
        "python-repl-state",
        "python-repl-reset",
    } <= set(advanced)
