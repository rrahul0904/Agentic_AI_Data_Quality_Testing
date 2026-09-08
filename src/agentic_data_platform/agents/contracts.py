from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum
from typing import Any

from agentic_data_platform.models import new_id, utc_now


class AgentRole(str, Enum):
    SUPERVISOR = "supervisor"
    METADATA = "metadata"
    BUSINESS_CONTEXT = "business_context"
    LINEAGE = "lineage"
    TRANSFORMATION = "transformation"
    MAPPING = "mapping"
    QUALITY = "quality"
    EXECUTION_PLANNING = "execution_planning"
    EVIDENCE = "evidence"
    RCA = "rca"
    IMPACT = "impact"
    REMEDIATION = "remediation"


class EvidenceTier(IntEnum):
    DIRECT_MEASUREMENT = 1
    RUNTIME_METADATA = 2
    STATIC_ANALYSIS = 3
    HISTORICAL_INFERENCE = 4
    LLM_INTERPRETATION = 5

    @property
    def label(self) -> str:
        return f"T{int(self)}"


class IncidentState(str, Enum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    RCA = "RCA"
    IMPACT_ANALYSIS = "IMPACT_ANALYSIS"
    REMEDIATION_PROPOSED = "REMEDIATION_PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REMEDIATING = "REMEDIATING"
    VERIFYING = "VERIFYING"
    RECERTIFYING = "RECERTIFYING"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class HypothesisStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class AgentPolicy:
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    model_tier: str = "deterministic-first"
    evidence_required: bool = True
    timeout_seconds: int = 30
    max_retries: int = 2
    max_tool_calls: int = 12


@dataclass(frozen=True)
class EvidenceRecord:
    kind: str
    source: str
    summary: str
    payload: dict[str, Any]
    tier: EvidenceTier = EvidenceTier.DIRECT_MEASUREMENT
    evidence_id: str = field(default_factory=lambda: new_id("evidence"))
    created_at: str = field(default_factory=utc_now)

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["tier"] = self.tier.label
        return value


@dataclass(frozen=True)
class AgentHypothesis:
    name: str
    statement: str
    status: HypothesisStatus
    confidence: float
    supporting_evidence_ids: tuple[str, ...] = ()
    contradictory_evidence_ids: tuple[str, ...] = ()
    hypothesis_id: str = field(default_factory=lambda: new_id("hypothesis"))

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


@dataclass(frozen=True)
class AgentResult:
    role: AgentRole
    status: str
    claim: str
    confidence: float
    supporting_evidence_ids: tuple[str, ...] = ()
    contradictory_evidence_ids: tuple[str, ...] = ()
    source_systems: tuple[str, ...] = ()
    affected_assets: tuple[str, ...] = ()
    reasoning_summary: str = ""
    next_recommended_action: str = ""
    observations: dict[str, Any] = field(default_factory=dict)
    tools_used: tuple[str, ...] = ()
    result_id: str = field(default_factory=lambda: new_id("agent_result"))
    created_at: str = field(default_factory=utc_now)

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["role"] = self.role.value
        return value


@dataclass(frozen=True)
class RemediationPlan:
    action: str
    reason: str
    evidence_ids: tuple[str, ...]
    risk: str
    blast_radius: tuple[str, ...]
    rollback: str
    verification_plan: tuple[str, ...]
    requires_approval: bool = True
    arguments: dict[str, Any] = field(default_factory=dict)
    plan_id: str = field(default_factory=lambda: new_id("remediation"))


@dataclass(frozen=True)
class InvestigationTransition:
    incident_id: str
    from_state: IncidentState | None
    to_state: IncidentState
    reason: str
    transition_id: str = field(default_factory=lambda: new_id("transition"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class InvestigationReport:
    incident_id: str
    scenario_id: str
    mode: str
    state: IncidentState
    anomaly: dict[str, Any]
    first_divergence: str | None
    root_cause: str | None
    root_cause_confidence: float
    hypotheses: tuple[AgentHypothesis, ...]
    blast_radius: tuple[str, ...]
    remediation: RemediationPlan | None
    certification: str
    agent_results: tuple[AgentResult, ...]
    evidence: tuple[EvidenceRecord, ...]
    transitions: tuple[InvestigationTransition, ...]
    approved: bool = False
    execution_result: dict[str, Any] = field(default_factory=dict)
    verification_result: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "scenario_id": self.scenario_id,
            "mode": self.mode,
            "state": self.state.value,
            "anomaly": self.anomaly,
            "first_divergence": self.first_divergence,
            "root_cause": self.root_cause,
            "root_cause_confidence": self.root_cause_confidence,
            "hypotheses": [item.public() for item in self.hypotheses],
            "blast_radius": list(self.blast_radius),
            "remediation": asdict(self.remediation) if self.remediation else None,
            "certification": self.certification,
            "agent_results": [item.public() for item in self.agent_results],
            "evidence": [item.public() for item in self.evidence],
            "transitions": [
                {
                    **asdict(item),
                    "from_state": item.from_state.value if item.from_state else None,
                    "to_state": item.to_state.value,
                }
                for item in self.transitions
            ],
            "approved": self.approved,
            "execution_result": self.execution_result,
            "verification_result": self.verification_result,
        }
