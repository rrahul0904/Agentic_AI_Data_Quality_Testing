"""Embeddable clients for the stable ADE API and governed in-process agent runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agentic_data_platform.models import ActorMode, Environment, InteractionMode, Platform, Risk, ToolRequest
from agentic_data_platform.runtime.agent import AgentRuntime
from agentic_data_platform.runtime.context import ContextManager
from agentic_data_platform.runtime.context_sources import ContextSourceManager
from agentic_data_platform.runtime.local_agent import (
    _BudgetedProvider,
    _scoped_read_only_registry,
    _system_prompt,
    agent_config,
    index_project_knowledge,
    provider_configured,
    runtime_store,
    trace_store,
    training_store,
)
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry
from agentic_data_platform.providers import ProviderRegistry


Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str]], Any]
ApprovalCallback = Callable[["ToolApprovalRequest"], bool]


def _transport(method: str, url: str, body: dict[str, Any] | None, headers: dict[str, str]) -> Any:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"platform HTTP {exc.code}: {raw[:2000]}") from exc
    except (URLError, OSError) as exc:
        raise RuntimeError(f"platform unavailable: {exc}") from exc


@dataclass(frozen=True)
class ToolApprovalRequest:
    """Exact, fingerprinted approval request exposed to SDK consumers."""

    tool: str
    operation: str
    risk: str
    environment: str
    args: dict[str, Any]
    platform: str | None
    scopes: tuple[str, ...]
    fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        tool: str,
        operation: str,
        risk: Risk,
        environment: Environment,
        args: dict[str, Any],
        platform: Platform | None,
        scopes: tuple[str, ...],
    ) -> "ToolApprovalRequest":
        payload = {
            "tool": tool,
            "operation": operation,
            "risk": risk.value,
            "environment": environment.value,
            "args": args,
            "platform": platform.value if platform else None,
            "scopes": list(scopes),
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return cls(
            tool=tool,
            operation=operation,
            risk=risk.value,
            environment=environment.value,
            args=dict(args),
            platform=platform.value if platform else None,
            scopes=scopes,
            fingerprint=fingerprint,
        )


class LocalAgentSession:
    """Persistent, project-scoped ADE agent session for embedding in applications.

    The same RuntimeStore, trace store, ToolRegistry policy, provider normalization,
    bounded context and project evidence hierarchy used by the product are reused here.
    SDK callers cannot silently bypass approval: any risky/direct tool invocation is
    surfaced through an exact fingerprinted callback before ToolRegistry execution.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        registry: ToolRegistry | None = None,
        provider: str | None = None,
        model: str | None = None,
        session_id: str | None = None,
        auto_index: bool = True,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        if not self.project_root.is_dir():
            raise FileNotFoundError(f"project root not found: {self.project_root}")
        self.registry = registry or build_tool_registry()
        self.config = agent_config(provider=provider, model=model)
        self.approval_callback = approval_callback
        self.store = runtime_store(self.project_root)
        self.traces = trace_store(self.project_root)
        self.training = training_store(self.project_root)
        self.index_result = (
            index_project_knowledge(self.project_root)
            if auto_index
            else {"status": "SKIP", "reason": "auto_index_disabled"}
        )
        existing = self.store.get_session(session_id) if session_id else None
        if session_id and existing is None:
            raise KeyError(f"unknown runtime session: {session_id}")
        self.session_id = session_id or self.store.create_session(
            project_id=str(self.project_root),
            title="Embedded ADE session",
            provider=str(self.config["provider"]),
            model=str(self.config["model"]),
        )
        if not existing:
            self.store.add_message(self.session_id, "system", _system_prompt(self.project_root))

    @property
    def provider_ready(self) -> bool:
        return provider_configured(str(self.config["provider"]))

    def history(self) -> list[dict[str, Any]]:
        return self.store.messages(self.session_id)

    def prompt(self, question: str) -> dict[str, Any]:
        question = str(question).strip()
        if not question:
            raise ValueError("question must not be empty")
        provider_name = str(self.config["provider"])
        if not self.provider_ready:
            return {
                "status": "BLOCKED_EXTERNAL",
                "session_id": self.session_id,
                "provider": provider_name,
                "model": self.config["model"],
                "error": f"provider {provider_name!r} is not configured",
            }

        provider = _BudgetedProvider(
            ProviderRegistry().create(provider_name),
            max_output_tokens=int(self.config["max_output_tokens"]),
            reasoning_effort=str(self.config["reasoning_effort"]),
        )
        context_tokens = int(self.config["context_tokens"])
        reserve_tokens = int(self.config["reserve_tokens"])
        if reserve_tokens >= context_tokens:
            reserve_tokens = max(2000, context_tokens // 4)
        runtime = AgentRuntime(
            _scoped_read_only_registry(self.registry, self.project_root),
            self.store,
            self.traces,
            context=ContextManager(max_tokens=context_tokens, reserve_tokens=reserve_tokens),
            context_sources=ContextSourceManager(training_store=self.training),
            max_steps=int(self.config["max_steps"]),
            repeated_tool_limit=2,
        )
        result = runtime.run(
            self.session_id,
            question,
            provider,
            str(self.config["model"]),
            actor_mode=ActorMode.ANALYST,
            project_root=self.project_root,
        )
        calls = self.store.tool_calls(self.session_id)
        return {
            "status": "PASS",
            "session_id": self.session_id,
            "trace_id": result.get("trace_id"),
            "response": result.get("response"),
            "steps": result.get("steps"),
            "provider": provider_name,
            "model": self.config["model"],
            "evidence": {
                "tools_used": [item["tool"] for item in calls],
                "context_sources": result.get("context_sources") or {},
                "project_index": self.index_result,
            },
        }

    def invoke_tool(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        operation: str | None = None,
        environment: str | Environment = Environment.DEV,
        platform: str | Platform | None = None,
        scopes: Iterable[str] = (),
        actor_mode: str | ActorMode = ActorMode.BUILDER,
        interaction_mode: str | InteractionMode = InteractionMode.AGENT,
        dry_run: bool = False,
        approval_callback: ApprovalCallback | None = None,
    ) -> dict[str, Any]:
        definition = self.registry.describe(name)
        env = environment if isinstance(environment, Environment) else Environment(str(environment))
        target = platform if isinstance(platform, Platform) or platform is None else Platform(str(platform))
        actor = actor_mode if isinstance(actor_mode, ActorMode) else ActorMode(str(actor_mode))
        interaction = (
            interaction_mode
            if isinstance(interaction_mode, InteractionMode)
            else InteractionMode(str(interaction_mode))
        )
        normalized_args = dict(args or {})
        normalized_scopes = tuple(sorted({str(item) for item in scopes}))
        approval = ToolApprovalRequest.create(
            tool=name,
            operation=operation or name,
            risk=definition.risk,
            environment=env,
            args=normalized_args,
            platform=target,
            scopes=normalized_scopes,
        )
        needs_approval = definition.requires_approval or definition.risk is not Risk.READ_ONLY
        callback = approval_callback or self.approval_callback
        approved = False
        if needs_approval:
            if callback is None:
                return {
                    "status": "APPROVAL_REQUIRED",
                    "session_id": self.session_id,
                    "approval": approval.__dict__,
                }
            approved = bool(callback(approval))
            if not approved:
                return {
                    "status": "DENIED",
                    "session_id": self.session_id,
                    "approval": approval.__dict__,
                }

        request = ToolRequest(
            tool=name,
            operation=operation or name,
            environment=env,
            risk=definition.risk,
            args=normalized_args,
            platform=target,
            scopes=normalized_scopes,
        )
        result = self.registry.invoke(
            ToolInvocation(
                request=request,
                run_id=self.session_id,
                approved=approved,
                dry_run=dry_run,
                actor_mode=actor,
                interaction_mode=interaction,
            )
        )
        return {
            "status": "PASS",
            "session_id": self.session_id,
            "tool": name,
            "approval_fingerprint": approval.fingerprint,
            "approved": approved,
            "result": result,
        }


class ADEClient:
    """Factory for persistent local ADE agent sessions."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        registry: ToolRegistry | None = None,
        provider: str | None = None,
        model: str | None = None,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.registry = registry or build_tool_registry()
        self.provider = provider
        self.model = model
        self.approval_callback = approval_callback

    def session(self, session_id: str | None = None, *, auto_index: bool = True) -> LocalAgentSession:
        return LocalAgentSession(
            self.project_root,
            registry=self.registry,
            provider=self.provider,
            model=self.model,
            session_id=session_id,
            auto_index=auto_index,
            approval_callback=self.approval_callback,
        )

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "risk": item.risk.value,
                "requires_approval": item.requires_approval,
                "platforms": sorted(platform.value for platform in item.supported_platforms),
                "input_schema": item.input_schema,
                "output_schema": item.output_schema,
            }
            for item in self.registry.definitions()
        ]


class PlatformClient:
    """Dependency-free HTTP client for the stable /api/v1 surface."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        token: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _transport
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/api/v1/"):
            raise ValueError("SDK only permits stable /api/v1 routes")
        url = f"{self.base_url}{path}"
        if query:
            encoded = urlencode({key: value for key, value in query.items() if value is not None})
            if encoded:
                url += f"?{encoded}"
        return self.transport(method.upper(), url, body, dict(self.headers))

    def get(self, path: str, **query: Any) -> Any:
        return self.request("GET", path, query=query or None)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("POST", path, body=body)

    def health(self) -> Any:
        return self.get("/api/v1/platform/health")

    def inventory(self) -> Any:
        return self.get("/api/v1/platform/inventory")

    def tools(self) -> Any:
        return self.get("/api/v1/tools")

    def domains(self) -> Any:
        return self.get("/api/v1/domains")

    def airflow_inventory(self) -> Any:
        return self.get("/api/v1/airflow/inventory")

    def airflow_assets(self) -> Any:
        return self.get("/api/v1/airflow/assets")

    def dbt_summary(self) -> Any:
        return self.get("/api/v1/dbt/summary")

    def providers(self) -> Any:
        return self.get("/api/v1/providers")

    def skills(self) -> Any:
        return self.get("/api/v1/skills/catalog")

    def agent_query(
        self,
        question: str,
        *,
        mode: str = "auto",
        provider: str | None = None,
        model: str | None = None,
    ) -> Any:
        return self.post(
            "/api/v1/agent/query",
            {"question": question, "mode": mode, "provider": provider, "model": model},
        )

    def knowledge_search(self, query: str, *, limit: int = 10) -> Any:
        return self.get("/api/v1/knowledge/search", query=query, limit=limit)

    def invoke_tool(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        actor_mode: str = "analyst",
        approved: bool = False,
        dry_run: bool = False,
    ) -> Any:
        return self.post(
            f"/api/v1/tools/{name}/invoke",
            {"args": args or {}, "actor_mode": actor_mode, "approved": approved, "dry_run": dry_run},
        )


HttpADEClient = PlatformClient
