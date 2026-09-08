from __future__ import annotations


import pytest

from agentic_data_platform.providers import (
    ModelRecord,
    ProviderResponse,
    ScriptedProvider,
    Usage,
)
from agentic_data_platform.session import (
    SessionRuntime,
    SessionStore,
    ValidationResult,
    ValidatorRegistry,
    cap_tool_result,
    deterministic_summary,
    load_instructions,
    retry_plan,
    session_overflow,
)
from agentic_data_platform.training import TrainingStore


def test_session_store_messages_errors_todos_reminders_state_revert(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session = store.create(title="Demo", provider="scripted", model="test")
    session_id = session["session_id"]
    assert store.get(session_id)["status"] == "IDLE"

    user = store.append_message(session_id, "user", "hello")
    assistant = store.append_message(
        session_id,
        "assistant",
        "working",
        error={"type": "warning", "message": "fixture"},
        metadata={"tool_calls": []},
    )
    assert user["sequence"] == 1
    assert assistant["sequence"] == 2
    assert assistant["error"]["type"] == "warning"

    todo = store.add_todo(session_id, "finish parity", priority=10)
    assert store.update_todo(todo["todo_id"], "IN_PROGRESS")["status"] == "IN_PROGRESS"
    reminder = store.add_reminder(
        session_id,
        "verify CI",
        {"type": "before_termination"},
    )
    assert store.reminders(session_id, undelivered_only=True)[0]["reminder_id"] == reminder["reminder_id"]
    assert store.mark_reminder_delivered(reminder["reminder_id"])["delivered"] is True

    assert store.patch_state(session_id, {"attempt": 2})["attempt"] == 2
    reverted = store.revert_last(session_id)
    assert reverted["reverted"] is True
    assert reverted["message"]["message_id"] == assistant["message_id"]
    assert [item["role"] for item in store.messages(session_id)] == ["user"]


def test_instruction_loading_and_prompt_training_reminders(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Always use deterministic evidence.")
    training = TrainingStore(tmp_path / "training.db")
    training.ingest_text("docs/reservation.md", "Reservation lineage uses reservation_id.")

    store = SessionStore(tmp_path / "sessions.db")
    runtime = SessionRuntime(store, training=training)
    session_id = runtime.create(title="Context")["session_id"]
    runtime.append(session_id, "user", "Review reservation lineage")
    store.add_reminder(session_id, "Run validators", {"type": "prompt"})

    instructions = load_instructions(tmp_path)
    assert instructions and instructions[0]["content"].startswith("Always")

    prompt = runtime.prompt(
        session_id,
        project_root=tmp_path,
        query="reservation lineage",
        system="You are a governed data engineering agent.",
    )
    assert prompt["messages"][0]["role"] == "system"
    system = prompt["messages"][0]["content"]
    assert "deterministic evidence" in system
    assert "Reservation lineage" in system
    assert "Run validators" in system
    assert prompt["training"]["applied_chunk_ids"]


def test_compaction_summary_tool_result_cap_retry_and_overflow(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    runtime = SessionRuntime(store)
    session_id = runtime.create()["session_id"]
    for index in range(12):
        runtime.append(
            session_id,
            "user" if index % 2 == 0 else "assistant",
            f"message-{index} " + ("x" * 200),
        )

    compacted = runtime.compact(session_id, keep_recent=4, summary_chars=600)
    assert compacted["status"] == "PASS"
    assert len(compacted["summary"]) <= 620
    assert compacted["state"]["compacted_through_sequence"] == 8

    summary = deterministic_summary(
        [{"role": "user", "content": "a" * 10000}],
        max_chars=500,
    )
    assert len(summary) <= 530
    capped = cap_tool_result({"payload": "x" * 10000}, max_chars=1000)
    assert capped["truncated"] is True
    assert capped["original_chars"] > 1000

    assert retry_plan(1, status_code=429)["retry"] is True
    assert retry_plan(5, status_code=429, max_attempts=5)["retry"] is False
    assert retry_plan(1, error="permanent syntax error")["retry"] is False

    small = ModelRecord(
        provider_id="fixture",
        model_id="tiny",
        name="Tiny",
        context_window=1200,
        max_output_tokens=1000,
    )
    overflow = session_overflow(
        small,
        [{"role": "user", "content": "x" * 5000}],
        requested_output_tokens=800,
    )
    assert overflow["overflow"] is True


def test_starvation_nudge_and_termination_validator_gate(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    validators = ValidatorRegistry()
    validators.register(
        "evidence",
        lambda context: ValidationResult(
            "evidence",
            bool(context.get("verified")),
            {"verified": bool(context.get("verified"))},
        ),
    )
    runtime = SessionRuntime(store, validators=validators)
    session_id = runtime.create()["session_id"]

    for index in range(3):
        runtime.append(session_id, "assistant", f"unsupported-{index}")
    nudge = runtime.nudge(session_id, threshold_assistant_messages=3)
    assert nudge["starved"] is True
    assert "deterministic tools" in nudge["nudge"]

    todo = store.add_todo(session_id, "finish tests")
    blocked = runtime.termination(
        session_id,
        validator_context={"verified": False},
    )
    assert blocked["can_terminate"] is False
    assert blocked["validation"]["blocking"] == ["evidence"]

    store.update_todo(todo["todo_id"], "DONE")
    allowed = runtime.termination(
        session_id,
        validator_context={"verified": True},
    )
    assert allowed["status"] == "PASS"
    assert allowed["can_terminate"] is True


def test_session_projector_and_status_lifecycle(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    runtime = SessionRuntime(store)
    session_id = runtime.create(title="Projection")["session_id"]
    runtime.append(session_id, "user", "hello")
    runtime.append(session_id, "assistant", "hi")
    store.add_todo(session_id, "todo")
    store.add_reminder(session_id, "reminder", {"type": "fixture"})
    store.patch_state(session_id, {"phase": "test"})

    projected = runtime.project(session_id)
    assert projected["role_counts"] == {"user": 1, "assistant": 1}
    assert projected["last_message"]["content"] == "hi"
    assert projected["state"]["phase"] == "test"

    assert store.set_status(session_id, "RUNNING")["status"] == "RUNNING"
    assert store.set_status(session_id, "COMPLETED")["status"] == "COMPLETED"
    with pytest.raises(ValueError):
        store.set_status(session_id, "INVALID")


def test_run_llm_persists_provider_response_and_usage(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    runtime = SessionRuntime(store)
    session_id = runtime.create(provider="scripted", model="fixture")["session_id"]
    runtime.append(session_id, "user", "answer this")
    provider = ScriptedProvider(
        [
            ProviderResponse(
                content="done",
                usage=Usage(input_tokens=12, output_tokens=3),
                finish_reason="stop",
            )
        ]
    )
    model = ModelRecord(
        provider_id="scripted",
        model_id="fixture",
        name="Fixture",
        context_window=32000,
        max_output_tokens=4000,
    )
    result = runtime.run_llm(
        session_id,
        provider=provider,
        provider_name="openai",
        model=model,
        requested_output_tokens=2000,
    )
    assert result["status"] == "PASS"
    assert result["response"]["content"] == "done"
    assert result["response"]["usage"]["input_tokens"] == 12
    assert store.get(session_id)["status"] == "IDLE"
    assert store.messages(session_id)[-1]["role"] == "assistant"


def test_validator_registry_duplicate_registration_is_rejected():
    registry = ValidatorRegistry()
    registry.register(
        "one",
        lambda context: ValidationResult("one", True, {}),
    )
    with pytest.raises(ValueError):
        registry.register(
            "one",
            lambda context: ValidationResult("one", True, {}),
        )
