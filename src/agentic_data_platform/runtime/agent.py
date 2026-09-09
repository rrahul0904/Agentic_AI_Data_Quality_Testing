from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from agentic_data_platform.models import ActorMode, Environment, Risk, ToolRequest, new_id
from agentic_data_platform.plugins import PluginBundleService, PluginManager
from agentic_data_platform.providers.base import Provider, ProviderRequest, ProviderResponse
from agentic_data_platform.runtime.context import ContextManager
from agentic_data_platform.runtime.context_sources import ContextSourceManager
from agentic_data_platform.runtime.store import RuntimeStore
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry
from agentic_data_platform.tracing.store import TraceStore


class AgentLoopError(RuntimeError):
    pass


class AgentRuntime:
    def __init__(
        self,
        registry: ToolRegistry,
        store: RuntimeStore,
        traces: TraceStore,
        *,
        context: ContextManager | None = None,
        context_sources: ContextSourceManager | None = None,
        plugins: PluginManager | None = None,
        max_steps: int = 12,
        repeated_tool_limit: int = 3,
    ) -> None:
        self.registry = registry
        self.store = store
        self.traces = traces
        self.context = context or ContextManager()
        self.context_sources = context_sources
        self.plugins = plugins or PluginManager()
        self.max_steps = max_steps
        self.repeated_tool_limit = repeated_tool_limit

    def _tool_specs(self, actor_mode: ActorMode) -> list[dict[str, Any]]:
        read_only_actor = actor_mode in {ActorMode.ANALYST, ActorMode.ASK, ActorMode.PLAN}
        return [
            {
                "name": item.name,
                "description": item.description,
                "input_schema": item.input_schema or {"type": "object"},
                "risk": item.risk.value,
            }
            for item in self.registry.definitions()
            if item.enabled and (not read_only_actor or item.risk is Risk.READ_ONLY)
        ]

    def _emit(self, hook: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.plugins.emit(hook, payload)]

    def run(
        self,
        session_id: str,
        user_message: str,
        provider: Provider,
        model: str,
        *,
        actor_mode: ActorMode = ActorMode.ANALYST,
        environment: Environment = Environment.DEV,
        approved_tools: set[str] | None = None,
        project_root: str | Path | None = None,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")

        approved_tools = approved_tools or set()

        def notify(event: str, **payload: Any) -> None:
            if event_handler is not None:
                event_handler({"event": event, "session_id": session_id, **payload})

        self.store.add_message(session_id, "user", user_message)
        notify("session.started", provider=provider.name, model=model, actor_mode=actor_mode.value)

        bundle_hook_state = (
            PluginBundleService(project_root).load_active_hooks(self.plugins)
            if project_root is not None
            else {"status": "PASS", "loaded": [], "failed": []}
        )

        selected_context = (
            self.context_sources.select(
                user_message,
                project_id=session.get("project_id"),
                project_root=project_root,
            )
            if self.context_sources is not None
            else None
        )
        selected_meta = selected_context.metadata() if selected_context else {
            "memory_ids": [],
            "training_ids": [],
            "training_chunk_ids": [],
            "skill_names": [],
        }

        trace_id = new_id("trace")
        session_payload = {
            "provider": provider.name,
            "model": model,
            "actor_mode": actor_mode.value,
            "environment": environment.value,
            "context_sources": selected_meta,
            "plugin_bundles": bundle_hook_state,
        }
        session_hooks = self._emit("session.start", {
            "session_id": session_id,
            "trace_id": trace_id,
            **session_payload,
        })
        root = self.traces.start(
            "session",
            "agent.run",
            trace_id=trace_id,
            session_id=session_id,
            payload={**session_payload, "plugins": session_hooks},
        )
        signatures: dict[str, int] = {}

        try:
            for step in range(1, self.max_steps + 1):
                stored = self.store.messages(session_id)
                messages = [
                    {
                        "role": message["role"],
                        "content": message["content"],
                        **message["metadata"],
                    }
                    for message in stored
                ]
                if selected_context:
                    messages = [*selected_context.messages, *messages]

                compacted, context_meta = self.context.compact(messages)
                snapshot_meta = {
                    **context_meta,
                    "selected_context": selected_meta,
                }
                self.store.add_context_snapshot(
                    session_id,
                    self.context.count_messages(compacted),
                    snapshot_meta,
                )

                before_hooks = self._emit("generation.before", {
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "step": step,
                    "provider": provider.name,
                    "model": model,
                    "context": snapshot_meta,
                })
                generation_event = self.traces.start(
                    "generation",
                    f"{provider.name}:{model}",
                    trace_id=trace_id,
                    session_id=session_id,
                    parent_id=root,
                    payload={
                        "step": step,
                        "context": snapshot_meta,
                        "plugins_before": before_hooks,
                    },
                )
                notify("generation.started", step=step, provider=provider.name, model=model)
                response: ProviderResponse = provider.generate(
                    ProviderRequest(
                        model=model,
                        messages=compacted,
                        tools=self._tool_specs(actor_mode),
                        metadata={
                            "session_id": session_id,
                            "step": step,
                            "context_sources": selected_meta,
                        },
                    )
                )
                generation_id = self.store.add_generation(
                    session_id,
                    provider.name,
                    model,
                    response.finish_reason,
                    asdict(response.usage),
                )
                after_hooks = self._emit("generation.after", {
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "generation_id": generation_id,
                    "step": step,
                    "finish_reason": response.finish_reason,
                    "usage": asdict(response.usage),
                    "tool_call_count": len(response.tool_calls),
                })
                self.traces.finish(
                    generation_event,
                    "SUCCESS",
                    {
                        "generation_id": generation_id,
                        "finish_reason": response.finish_reason,
                        "usage": asdict(response.usage),
                        "tool_call_count": len(response.tool_calls),
                        "plugins_after": after_hooks,
                    },
                )
                notify(
                    "generation.finished",
                    step=step,
                    finish_reason=response.finish_reason,
                    usage=asdict(response.usage),
                    tool_call_count=len(response.tool_calls),
                    content=response.content,
                )

                if response.content or response.tool_calls:
                    assistant_metadata: dict[str, Any] = {}
                    if response.tool_calls:
                        assistant_metadata["tool_calls"] = [
                            {"id": call.call_id, "name": call.name, "args": dict(call.args)}
                            for call in response.tool_calls
                        ]
                    self.store.add_message(
                        session_id,
                        "assistant",
                        response.content or "",
                        assistant_metadata,
                    )

                if not response.tool_calls:
                    end_hooks = self._emit("session.end", {
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "status": "SUCCESS",
                        "steps": step,
                    })
                    self.traces.finish(
                        root,
                        "SUCCESS",
                        {"steps": step, "plugins_end": end_hooks},
                    )
                    notify("session.finished", status="SUCCESS", steps=step, trace_id=trace_id)
                    return {
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "response": response.content,
                        "steps": step,
                        "finish_reason": response.finish_reason,
                        "context_sources": selected_meta,
                    }

                for call in response.tool_calls:
                    definition = self.registry.describe(call.name)
                    signature = f"{call.name}:{json.dumps(call.args, sort_keys=True, default=str)}"
                    signatures[signature] = signatures.get(signature, 0) + 1
                    if signatures[signature] > self.repeated_tool_limit:
                        raise AgentLoopError(f"repeated tool loop detected: {call.name}")

                    tool_decision = self.plugins.evaluate("tool.before", {
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "generation_id": generation_id,
                        "tool": call.name,
                        "args": dict(call.args),
                        "risk": definition.risk.value,
                    })
                    before_tool_hooks = tool_decision.public()["results"]
                    effective_args = tool_decision.payload.get("args", dict(call.args))
                    if not isinstance(effective_args, dict):
                        raise ValueError("tool.before hook must preserve args as an object")
                    effective_args = dict(effective_args)
                    approval_was_modified = bool(
                        tool_decision.modified
                        and effective_args != dict(call.args)
                        and definition.requires_approval
                    )
                    effective_approved = bool(
                        call.name in approved_tools and not approval_was_modified
                    )
                    permission_decision = self.plugins.evaluate("permission.before", {
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "tool": call.name,
                        "actor_mode": actor_mode.value,
                        "environment": environment.value,
                        "approved": effective_approved,
                        "risk": definition.risk.value,
                    })
                    permission_hooks = permission_decision.public()["results"]
                    tool_event = self.traces.start(
                        "tool",
                        call.name,
                        trace_id=trace_id,
                        session_id=session_id,
                        parent_id=generation_event,
                        payload={
                            "args": effective_args,
                            "original_args": dict(call.args),
                            "risk": definition.risk.value,
                            "plugins_before": before_tool_hooks,
                            "permission_plugins": permission_hooks,
                            "hook_modified": tool_decision.modified,
                            "approval_invalidated_by_hook": approval_was_modified,
                        },
                    )
                    tool_call_id = self.store.start_tool_call(
                        session_id,
                        generation_id,
                        call.name,
                        effective_args,
                        call.call_id,
                    )
                    request = ToolRequest(
                        tool=call.name,
                        operation=call.name,
                        environment=environment,
                        risk=definition.risk,
                        args=effective_args,
                    )
                    requires_approval = bool(
                        definition.requires_approval
                        or (
                            environment is Environment.PROD
                            and definition.risk.value == "mutating"
                        )
                    )
                    notify(
                        "tool.started",
                        step=step,
                        tool=call.name,
                        args=dict(call.args),
                        risk=definition.risk.value,
                        requires_approval=requires_approval,
                        approved=effective_approved,
                        hook_modified=tool_decision.modified,
                    )
                    if tool_decision.blocked:
                        notify("tool.blocked", tool=call.name, reason=tool_decision.reason)
                    if permission_decision.blocked:
                        notify("tool.blocked", tool=call.name, reason=permission_decision.reason)
                    if requires_approval and not effective_approved:
                        notify("approval.required", tool=call.name, risk=definition.risk.value)
                    try:
                        if tool_decision.blocked:
                            raise PermissionError(tool_decision.reason or f"tool blocked by plugin: {call.name}")
                        if permission_decision.blocked:
                            raise PermissionError(permission_decision.reason or f"permission blocked by plugin: {call.name}")
                        result = self.registry.invoke(
                            ToolInvocation(
                                request,
                                run_id=session_id,
                                approved=effective_approved,
                                actor_mode=actor_mode,
                            )
                        )
                        status = "SUCCESS"
                    except Exception as exc:
                        result = {
                            "error": type(exc).__name__,
                            "message": str(exc),
                        }
                        status = "DENIED" if isinstance(exc, PermissionError) else "ERROR"

                    self.store.finish_tool_call(tool_call_id, result, status)
                    notify("tool.finished", tool=call.name, status=status, result=result)
                    after_tool_hooks = self._emit("tool.after", {
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "generation_id": generation_id,
                        "tool_call_id": tool_call_id,
                        "tool": call.name,
                        "status": status,
                        "result": result,
                    })
                    self.traces.finish(
                        tool_event,
                        status,
                        {
                            "result": result,
                            "plugins_after": after_tool_hooks,
                        },
                    )
                    self.store.add_message(
                        session_id,
                        "tool",
                        json.dumps(result, default=str),
                        {
                            "tool_call_id": call.call_id,
                            "name": call.name,
                            "status": status,
                        },
                    )

            raise AgentLoopError(f"maximum agent steps exceeded: {self.max_steps}")
        except Exception as exc:
            end_hooks = self._emit("session.end", {
                "session_id": session_id,
                "trace_id": trace_id,
                "status": "ERROR",
                "error": type(exc).__name__,
                "message": str(exc),
            })
            notify("session.finished", status="ERROR", error=type(exc).__name__, message=str(exc), trace_id=trace_id)
            self.traces.finish(
                root,
                "ERROR",
                {
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "plugins_end": end_hooks,
                },
            )
            raise
