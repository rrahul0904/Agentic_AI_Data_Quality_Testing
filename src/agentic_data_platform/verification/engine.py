from __future__ import annotations
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from agentic_data_platform.models import VerificationFinding, VerificationReport
Check = Callable[[], VerificationFinding]

@dataclass(frozen=True)
class VerificationGate:
    name: str
    check: Check
    blocking: bool = True

class VerificationEngine:
    def run(self, checks: Iterable[Check]) -> VerificationReport:
        report=VerificationReport()
        for check in checks:
            try: report.add(check())
            except Exception as exc: report.add(VerificationFinding(getattr(check,"__name__","unknown"),False,detail=str(exc)))
        return report

    def run_ordered(self, gates: Iterable[VerificationGate], *, run_id: str | None = None) -> VerificationReport:
        report=VerificationReport(run_id=run_id)
        for gate in gates:
            try:
                finding=gate.check()
                if finding.blocking != gate.blocking: finding=VerificationFinding(finding.check,finding.passed,finding.severity,finding.detail,gate.blocking,finding.evidence)
            except Exception as exc: finding=VerificationFinding(gate.name,False,detail=str(exc),blocking=gate.blocking)
            report.add(finding)
            if not finding.passed and finding.severity=="error" and finding.blocking: break
        return report
