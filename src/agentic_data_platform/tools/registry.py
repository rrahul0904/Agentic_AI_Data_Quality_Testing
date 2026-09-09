from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from agentic_data_platform.models import ActorMode, Capability, InteractionMode, Platform, Risk, ToolRequest
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
    interaction_mode: InteractionMode = InteractionMode.AGENT

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

    @staticmethod
    def allowed_in_interaction_mode(
        definition: ToolDefinition,
        mode: InteractionMode,
    ) -> bool:
        if mode in {InteractionMode.ASK, InteractionMode.PLAN}:
            return definition.risk is Risk.READ_ONLY

        name = definition.name.casefold()
        if mode is InteractionMode.EDIT:
            if definition.risk is Risk.READ_ONLY:
                return not name.startswith(
                    (
                        "snowflake_mutation",
                        "dbt_",
                        "notebook_",
                        "mcp_",
                        "skill_",
                        "automation_",
                        "hosted_runner_",
                    )
                )
            return name == "workspace_region_edit_apply"

        if mode is InteractionMode.CODE:
            denied_prefixes = (
                "snowflake_",
                "dbt_",
                "notebook_",
                "mcp_",
                "skill_",
                "automation_",
                "hosted_runner_",
                "cortex_",
                "semantic_",
                "app_deploy",
                "account_",
                "admin_",
                "governance_grant",
            )
            if name.startswith(denied_prefixes):
                return False
            if definition.risk is Risk.READ_ONLY:
                return True
            coding_mutation_prefixes = (
                "workspace_",
                "shell_",
                "sandbox_shell_",
                "git_",
                "job_",
                "python_repl_",
                "session_todo_",
            )
            return name.startswith(coding_mutation_prefixes)

        return True

    def definitions_for_mode(
        self,
        mode: InteractionMode,
    ) -> tuple[ToolDefinition, ...]:
        return tuple(
            definition
            for definition in self.definitions()
            if definition.enabled and self.allowed_in_interaction_mode(definition, mode)
        )

    def invoke(self, invocation: ToolInvocation) -> dict[str, Any]:
        definition = self.describe(invocation.request.tool)
        if not definition.enabled:
            raise PermissionError(f"tool {definition.name} is disabled")
        request = invocation.request
        if not self.allowed_in_interaction_mode(definition, invocation.interaction_mode):
            raise PermissionError(
                f"{invocation.interaction_mode.value} interaction mode cannot invoke {definition.name}"
            )
        if invocation.actor_mode in {ActorMode.ANALYST, ActorMode.ASK, ActorMode.PLAN} and definition.risk is not Risk.READ_ONLY:
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
        args["_interaction_mode"] = invocation.interaction_mode.value
        return definition.handler(args)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return stable metadata without exposing mutable registry state."""

        return tuple(self._tools[name] for name in sorted(self._tools))
