from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RepairAttempt:
    number: int
    diagnosis: str
    changed_artifact: str | None
    verification_evidence: dict[str, object]
    succeeded: bool


class RepairAgent:
    """Runs a fixed number of caller-supplied sandbox repair attempts."""

    def __init__(self, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.max_attempts = max_attempts

    def repair(self, diagnose: Callable[[], str], propose_and_verify: Callable[[str, int], tuple[str | None, dict[str, object], bool]]) -> list[RepairAttempt]:
        attempts: list[RepairAttempt] = []
        for number in range(1, self.max_attempts + 1):
            diagnosis = diagnose()
            artifact, evidence, succeeded = propose_and_verify(diagnosis, number)
            attempts.append(RepairAttempt(number, diagnosis, artifact, evidence, succeeded))
            if succeeded:
                break
        return attempts
