from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from agentic_data_platform.models import ActorMode, Capability, Platform, Risk, ToolRequest
from agentic_data_platform.policy import PolicyEngine

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

@dataclass(frozen=True)
class ToolDefinition:
    name: str
    capability: Capability
    risk: Risk
    supported_platforms: frozenset[Platform]
    handler: ToolHandler = field(repr=False, compare=False)
    required_scopes: frozenset[str] = frozenset()
    supports_dry_run: bool = False
    requires_approval: bool = False
    enabled: bool = True
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict, compare=False)
    output_schema: dict[str, Any] = field(default_factory=dict, compare=False)

@dataclass(frozen=True)
class ToolInvocation:
    request: ToolRequest
    run_id: str
    approved: bool = False
    dry_run: bool = False
    actor_mode: ActorMode = ActorMode.BUILDER

class ToolRegistry:
    """The only supported execution path for external tools and platform mutations."""
    def __init__(self, policy: PolicyEngine | None = None) -> None:
        self._policy = policy or PolicyEngine()
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def describe(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def invoke(self, invocation: ToolInvocation) -> dict[str, Any]:
        definition = self.describe(invocation.request.tool)
        if not definition.enabled:
            raise PermissionError(f"tool {definition.name} is disabled")
        request = invocation.request
        if invocation.actor_mode in {ActorMode.ANALYST, ActorMode.PLAN} and definition.risk is not Risk.READ_ONLY:
            raise PermissionError(f"{invocation.actor_mode.value} mode cannot invoke {definition.risk.value} tools")
        if request.risk is not definition.risk:
            raise PermissionError("request risk does not match registered tool risk")
        if request.platform is not None and request.platform not in definition.supported_platforms:
            raise ValueError(f"platform {request.platform.value} is not supported by {definition.name}")
        missing_scopes = definition.required_scopes.difference(request.scopes)
        if missing_scopes:
            raise PermissionError(f"missing required scopes: {', '.join(sorted(missing_scopes))}")
        if invocation.dry_run and not definition.supports_dry_run:
            raise ValueError(f"tool {definition.name} does not support dry-run")
        decision = self._policy.evaluate(request)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if decision.requires_approval and not invocation.approved:
            raise PermissionError("explicit approval required before tool execution")
        if definition.requires_approval and not invocation.approved:
            raise PermissionError("explicit approval required before external or workspace mutation")
        args = dict(request.args)
        args["_run_id"] = invocation.run_id
        args["_dry_run"] = invocation.dry_run
        args["_approved"] = invocation.approved
        args["_environment"] = request.environment.value
        args["_actor_mode"] = invocation.actor_mode.value
        return definition.handler(args)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return stable metadata without exposing mutable registry state."""

        return tuple(self._tools[name] for name in sorted(self._tools))
