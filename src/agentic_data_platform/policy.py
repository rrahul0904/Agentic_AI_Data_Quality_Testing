from __future__ import annotations

from .models import Environment, PolicyDecision, Risk, ToolRequest


class PolicyEngine:
    """Deterministic authorization boundary for agent-requested operations."""

    def evaluate(self, request: ToolRequest) -> PolicyDecision:
        if request.risk is Risk.DESTRUCTIVE:
            return PolicyDecision(False, reason="destructive operations are blocked by default")
        if request.environment is Environment.PROD and request.risk is Risk.MUTATING:
            return PolicyDecision(True, requires_approval=True, reason="production mutation requires approval")
        return PolicyDecision(True, reason="operation permitted by baseline policy")
