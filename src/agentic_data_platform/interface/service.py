"""Shared application service for CLI, TUI and API-facing interfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.platform.discovery import render_discovery
from agentic_data_platform.providers import ProviderRegistry
from agentic_data_platform.runtime.agent import AgentRuntime
from agentic_data_platform.runtime.store import RuntimeStore
from agentic_data_platform.runtime.replay import replay_session
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry
from agentic_data_platform.tracing.store import TraceStore


class AgenticService:
    """One governed service facade shared by interactive interfaces."""

    def __init__(
        self,
        project_root: str | Path = ".",
        *,
        actor_mode: ActorMode = ActorMode.ANALYST,
        provider: str | None = None,
        model: str | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.actor_mode = actor_mode
        self.provider_name = provider
        self.model = model
        self.registry = registry or build_tool_registry()
        self.state_root = self.project_root / ".ade"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.runtime_store = RuntimeStore(self.state_root / "runtime.db")
        self.trace_store = TraceStore(self.state_root / "traces.db")
        self.provider_registry = ProviderRegistry()
        self.session_id = self.runtime_store.create_session(
            project_id=str(self.project_root),
            title="Agentic TUI",
            provider=provider or "",
            model=model or "",
        )

    def set_mode(self, mode: str | ActorMode) -> ActorMode:
        self.actor_mode = mode if isinstance(mode, ActorMode) else ActorMode(str(mode).casefold())
        return self.actor_mode

    def set_provider(self, provider: str | None, model: str | None = None) -> None:
        self.provider_name = provider
        if model is not None:
            self.model = model

    def invoke(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        *,
        approved: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        definition = self.registry.describe(tool_name)
        payload = dict(args or {})
        if "project" not in payload and "project_path" not in payload and "target_dir" not in payload:
            payload["project"] = str(self.project_root)
        request = ToolRequest(
            tool=tool_name,
            operation=tool_name,
            environment=Environment.DEV,
            risk=definition.risk,
            args=payload,
        )
        return self.registry.invoke(
            ToolInvocation(
                request,
                run_id=self.session_id,
                approved=approved,
                dry_run=dry_run,
                actor_mode=self.actor_mode,
            )
        )

    def discover(self) -> dict[str, Any]:
        return self.invoke("platform_discover", {"project": str(self.project_root)})

    def discover_text(self) -> str:
        return render_discovery(self.discover())

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "risk": item.risk.value,
                "capability": item.capability.value,
                "requires_approval": item.requires_approval,
            }
            for item in self.registry.definitions()
            if item.enabled
        ]

    def sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.runtime_store.list_sessions(limit=limit)

    def traces(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.trace_store.traces(limit=limit)

    def replay_trace(self, trace_id: str) -> dict[str, Any]:
        return self.trace_store.replay(trace_id)

    def session_replay(self, session_id: str) -> dict[str, Any]:
        return replay_session(self.runtime_store, self.trace_store, session_id)

    def provider_status(self) -> list[dict[str, Any]]:
        return self.provider_registry.specs()

    def ask(
        self,
        message: str,
        *,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
        approved_tools: set[str] | None = None,
    ) -> dict[str, Any]:
        if not self.provider_name or not self.model:
            return {
                "status": "SKIP_EXTERNAL",
                "reason": "No live provider/model is selected. Use /providers and configure a provider before natural-language chat.",
                "session_id": self.session_id,
            }
        specs = {str(item["name"]): item for item in self.provider_registry.specs()}
        spec = specs.get(self.provider_name)
        if spec is None:
            raise KeyError(f"provider not registered: {self.provider_name}")
        if not spec.get("configured"):
            return {
                "status": "SKIP_EXTERNAL",
                "reason": f"{self.provider_name} is not configured",
                "session_id": self.session_id,
            }
        provider = self.provider_registry.create(self.provider_name)
        runtime = AgentRuntime(
            self.registry,
            self.runtime_store,
            self.trace_store,
        )
        result = runtime.run(
            self.session_id,
            message,
            provider,
            self.model,
            actor_mode=self.actor_mode,
            approved_tools=approved_tools,
            project_root=self.project_root,
            event_handler=event_handler,
        )
        return {"status": "PASS", **result}

    def status(self) -> dict[str, Any]:
        return {
            "project": str(self.project_root),
            "mode": self.actor_mode.value.upper(),
            "provider": self.provider_name,
            "model": self.model,
            "session_id": self.session_id,
            "tool_count": len(self.registry.definitions()),
        }
