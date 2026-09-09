"""Session runtime: prompts, compaction, retry, LLM execution and termination gates."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agentic_data_platform.observability import TraceStore
from agentic_data_platform.providers import (
    ModelRecord,
    Provider,
    ProviderRequest,
    normalize_messages,
    output_token_budget,
)
from agentic_data_platform.session.store import SessionStore
from agentic_data_platform.rules import RuleStore
from agentic_data_platform.training import TrainingStore


@dataclass(frozen=True)
class ValidationResult:
    name: str
    ok: bool
    details: dict[str, Any]


class ValidatorRegistry:
    def __init__(self) -> None:
        self._validators: dict[str, Callable[[dict[str, Any]], ValidationResult]] = {}

    def register(
        self,
        name: str,
        validator: Callable[[dict[str, Any]], ValidationResult],
    ) -> None:
        if name in self._validators:
            raise ValueError(f"validator already registered: {name}")
        self._validators[name] = validator

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._validators))

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        results = [self._validators[name](context) for name in self.names()]
        return {
            "status": "PASS" if all(item.ok for item in results) else "FAIL",
            "results": [asdict(item) for item in results],
            "blocking": [item.name for item in results if not item.ok],
        }


def load_instructions(
    project_root: str | Path,
    *,
    target_path: str | None = None,
    global_root: str | Path | None = None,
) -> list[dict[str, str]]:
    resolved = RuleStore(
        project_root,
        global_root=global_root,
    ).resolve(target_path=target_path)
    return [
        {
            "path": str(item.get("path") or item.get("source") or item["name"]),
            "content": str(item["content"]),
            "name": str(item["name"]),
            "scope": str(item["scope"]),
            "rule_fingerprint": str(item["rule_fingerprint"]),
        }
        for item in resolved["rules"]
    ]

def cap_tool_result(value: Any, *, max_chars: int = 20000) -> dict[str, Any]:
    raw = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    if len(raw) <= max_chars:
        return {"content": raw, "truncated": False, "original_chars": len(raw)}
    head = max_chars * 2 // 3
    tail = max_chars - head
    content = (
        raw[:head]
        + "\n...[tool result truncated; original_chars="
        + str(len(raw))
        + "]...\n"
        + raw[-tail:]
    )
    return {"content": content, "truncated": True, "original_chars": len(raw)}


def retry_plan(
    attempt: int,
    *,
    error: str | None = None,
    status_code: int | None = None,
    max_attempts: int = 5,
    base_seconds: float = 1.0,
    max_seconds: float = 30.0,
) -> dict[str, Any]:
    retryable_status = status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    text = (error or "").casefold()
    retryable_text = any(
        token in text
        for token in (
            "rate limit",
            "timeout",
            "temporar",
            "connection reset",
            "overloaded",
            "unavailable",
        )
    )
    retryable = retryable_status or retryable_text
    if attempt >= max_attempts:
        retryable = False
    delay = min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    return {
        "attempt": attempt,
        "max_attempts": max_attempts,
        "retry": retryable,
        "delay_seconds": delay if retryable else 0,
        "reason": (
            "transient provider/runtime failure"
            if retryable
            else "non-retryable or retry budget exhausted"
        ),
    }


def deterministic_summary(messages: Sequence[Mapping[str, Any]], *, max_chars: int = 8000) -> str:
    lines = []
    for message in messages:
        role = str(message.get("role") or "unknown").upper()
        content = message.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, default=str)
        cleaned = " ".join(content.split())
        if not cleaned:
            continue
        lines.append(f"{role}: {cleaned[:1200]}")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return text[:head] + "\n...[compacted]...\n" + text[-tail:]


def session_overflow(
    model: ModelRecord,
    messages: Sequence[Mapping[str, Any]],
    *,
    requested_output_tokens: int | None = None,
) -> dict[str, Any]:
    try:
        budget = output_token_budget(
            model,
            messages,
            requested=requested_output_tokens,
        )
        return {"status": "PASS", "overflow": False, "budget": budget}
    except Exception as exc:
        return {
            "status": "OVERFLOW",
            "overflow": True,
            "error": str(exc),
        }


class SessionRuntime:
    def __init__(
        self,
        store: SessionStore,
        *,
        training: TrainingStore | None = None,
        traces: TraceStore | None = None,
        validators: ValidatorRegistry | None = None,
    ) -> None:
        self.store = store
        self.training = training
        self.traces = traces
        self.validators = validators or ValidatorRegistry()

    def create(
        self,
        *,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.store.create(
            title=title,
            provider=provider,
            model=model,
            metadata=metadata,
        )
        if self.traces:
            self.traces.start(
                trace_id=session["session_id"],
                session_id=session["session_id"],
                title=title,
                metadata={"provider": provider, "model": model},
            )
        return session

    def append(self, session_id: str, role: str, content: Any, **kwargs: Any) -> dict[str, Any]:
        message = self.store.append_message(session_id, role, content, **kwargs)
        if self.traces:
            self.traces.event(
                session_id,
                "message",
                role,
                metadata={
                    "message_id": message["message_id"],
                    "sequence": message["sequence"],
                },
            )
        return message

    def prompt(
        self,
        session_id: str,
        *,
        project_root: str | Path | None = None,
        query: str | None = None,
        system: str | None = None,
        include_training: bool = True,
        training_limit: int = 6,
        training_chars: int = 10000,
    ) -> dict[str, Any]:
        messages = self.store.messages(session_id)
        prompt_messages: list[dict[str, Any]] = []
        system_parts = []
        if system:
            system_parts.append(system)
        instructions = load_instructions(project_root) if project_root else []
        for item in instructions:
            system_parts.append(
                "Project instruction from "
                + item["path"]
                + ":\n"
                + item["content"]
            )
        training_context = None
        if include_training and self.training and query:
            training_context = self.training.context(
                query,
                limit=training_limit,
                max_chars=training_chars,
            )
            if training_context["chunks"]:
                system_parts.append(
                    "Retrieved project training context:\n"
                    + "\n\n".join(
                        f"[{item['source']}#{item['chunk_index']}]\n{item['content']}"
                        for item in training_context["chunks"]
                    )
                )
        reminders = self.store.reminders(session_id, undelivered_only=True)
        if reminders:
            system_parts.append(
                "Session reminders:\n"
                + "\n".join("- " + item["text"] for item in reminders)
            )
        if system_parts:
            prompt_messages.append(
                {
                    "role": "system",
                    "content": "\n\n".join(system_parts),
                }
            )
        for message in messages:
            prompt_messages.append(
                {
                    "role": message["role"],
                    "content": message["content"],
                }
            )
        return {
            "session_id": session_id,
            "messages": prompt_messages,
            "instructions": instructions,
            "training": training_context,
            "reminders": reminders,
        }

    def compact(
        self,
        session_id: str,
        *,
        keep_recent: int = 8,
        summary_chars: int = 8000,
    ) -> dict[str, Any]:
        messages = self.store.messages(session_id)
        if len(messages) <= keep_recent:
            return {
                "status": "NOOP",
                "session_id": session_id,
                "message_count": len(messages),
            }
        older = messages[:-keep_recent]
        recent = messages[-keep_recent:]
        summary = deterministic_summary(
            [
                {"role": item["role"], "content": item["content"]}
                for item in older
            ],
            max_chars=summary_chars,
        )
        state = self.store.patch_state(
            session_id,
            {
                "compaction_summary": summary,
                "compacted_through_sequence": older[-1]["sequence"],
            },
        )
        if self.traces:
            self.traces.event(
                session_id,
                "compaction",
                "session_compact",
                metadata={
                    "older_messages": len(older),
                    "recent_messages": len(recent),
                    "summary_chars": len(summary),
                },
            )
        return {
            "status": "PASS",
            "session_id": session_id,
            "summary": summary,
            "recent_messages": recent,
            "state": state,
        }

    def nudge(
        self,
        session_id: str,
        *,
        threshold_assistant_messages: int = 3,
    ) -> dict[str, Any]:
        messages = self.store.messages(session_id)
        tail = messages[-threshold_assistant_messages:]
        starved = (
            len(tail) >= threshold_assistant_messages
            and all(item["role"] == "assistant" for item in tail)
            and not any(item["metadata"].get("tool_calls") for item in tail)
        )
        if not starved:
            return {"status": "PASS", "nudge": None, "starved": False}
        text = (
            "Use deterministic tools to gather evidence before continuing. "
            "Do not repeat unsupported conclusions."
        )
        self.store.patch_state(
            session_id,
            {"last_nudge": text, "starvation_detected": True},
        )
        return {"status": "WARN", "nudge": text, "starved": True}

    def termination(
        self,
        session_id: str,
        *,
        validator_context: dict[str, Any] | None = None,
        require_todos_complete: bool = True,
    ) -> dict[str, Any]:
        todos = self.store.todos(session_id)
        open_todos = [
            item for item in todos
            if item["status"] != "DONE"
        ]
        validation = self.validators.run(validator_context or {})
        blocked = (
            (require_todos_complete and bool(open_todos))
            or validation["status"] != "PASS"
        )
        return {
            "status": "BLOCKED" if blocked else "PASS",
            "can_terminate": not blocked,
            "open_todos": open_todos,
            "validation": validation,
        }

    def run_llm(
        self,
        session_id: str,
        *,
        provider: Provider,
        provider_name: str,
        model: ModelRecord,
        tools: Sequence[dict[str, Any]] = (),
        project_root: str | Path | None = None,
        query: str | None = None,
        system: str | None = None,
        requested_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        session = self.store.get(session_id)
        prompt = self.prompt(
            session_id,
            project_root=project_root,
            query=query,
            system=system,
        )
        normalized = normalize_messages(
            prompt["messages"],
            provider=provider_name,
            model_id=model.model_id,
        )
        budget = output_token_budget(
            model,
            normalized,
            requested=requested_output_tokens,
        )
        request = ProviderRequest(
            model=model.model_id,
            messages=normalized,
            tools=tools,
            temperature=temperature,
            max_output_tokens=budget["allowed"],
            metadata={"session_id": session_id},
        )
        self.store.set_status(session_id, "RUNNING")
        started = time.perf_counter()
        try:
            response = provider.generate(request)
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            self.store.set_status(session_id, "FAILED")
            if self.traces:
                self.traces.event(
                    session_id,
                    "provider",
                    provider_name,
                    status="FAIL",
                    duration_ms=duration,
                    provider=provider_name,
                    model=model.model_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            raise
        duration = (time.perf_counter() - started) * 1000
        message = self.append(
            session_id,
            "assistant",
            response.content,
            metadata={
                "tool_calls": [asdict(call) for call in response.tool_calls],
                "finish_reason": response.finish_reason,
            },
        )
        self.store.set_status(session_id, "IDLE")
        if self.traces:
            self.traces.event(
                session_id,
                "provider",
                provider_name,
                status="PASS",
                duration_ms=duration,
                provider=provider_name,
                model=model.model_id,
                usage=asdict(response.usage),
                metadata={
                    "finish_reason": response.finish_reason,
                    "tool_call_count": len(response.tool_calls),
                },
            )
        return {
            "status": "PASS",
            "session": session,
            "message": message,
            "response": {
                "content": response.content,
                "tool_calls": [asdict(call) for call in response.tool_calls],
                "usage": asdict(response.usage),
                "finish_reason": response.finish_reason,
            },
            "budget": budget,
        }

    def project(self, session_id: str) -> dict[str, Any]:
        session = self.store.get(session_id)
        messages = self.store.messages(session_id)
        role_counts: dict[str, int] = {}
        for message in messages:
            role_counts[message["role"]] = role_counts.get(message["role"], 0) + 1
        return {
            "session": session,
            "role_counts": role_counts,
            "last_message": messages[-1] if messages else None,
            "todos": self.store.todos(session_id),
            "reminders": self.store.reminders(session_id),
            "state": self.store.state(session_id),
        }
