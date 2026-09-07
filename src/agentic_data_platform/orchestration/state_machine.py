from __future__ import annotations

from dataclasses import dataclass
from agentic_data_platform.models import RunState

_ALLOWED: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.DISCOVERING, RunState.CANCELLED},
    RunState.DISCOVERING: {RunState.PLANNING, RunState.FAILED, RunState.CANCELLED},
    RunState.PLANNING: {RunState.GENERATING, RunState.FAILED, RunState.CANCELLED},
    RunState.GENERATING: {RunState.VERIFYING, RunState.FAILED, RunState.CANCELLED},
    RunState.VERIFYING: {RunState.AWAITING_APPROVAL, RunState.EXECUTING, RunState.REPAIRING, RunState.FAILED},
    RunState.AWAITING_APPROVAL: {RunState.EXECUTING, RunState.CANCELLED, RunState.FAILED},
    RunState.EXECUTING: {RunState.SUCCEEDED, RunState.REPAIRING, RunState.FAILED, RunState.CANCELLED},
    RunState.REPAIRING: {RunState.VERIFYING, RunState.FAILED, RunState.CANCELLED},
    RunState.SUCCEEDED: set(), RunState.FAILED: set(), RunState.CANCELLED: set(),
}

@dataclass
class RunStateMachine:
    state: RunState = RunState.CREATED
    repair_attempts: int = 0
    max_repairs: int = 3

    def transition(self, target: RunState) -> None:
        if target not in _ALLOWED[self.state]:
            raise ValueError(f"invalid transition: {self.state.value} -> {target.value}")
        if target is RunState.REPAIRING:
            if self.repair_attempts >= self.max_repairs:
                raise RuntimeError("repair budget exhausted")
            self.repair_attempts += 1
        self.state = target
