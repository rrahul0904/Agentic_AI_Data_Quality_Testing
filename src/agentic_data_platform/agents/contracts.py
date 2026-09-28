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
    DIRECT_EXECUTION = 1
    RUNTIME_STATE = 2
    TASK_PROCESS_LOG = 3
    ORCHESTRATOR_METADATA = 4
    DEPENDENCY_RESPONSE = 5
    DATA_STATE = 6
    STATIC_ANALYSIS = 7
    LLM_INFERENCE = 8

    # Backwards-compatible names used by existing agents and persisted fixtures.
    DIRECT_MEASUREMENT = DIRECT_EXECUTION
    RUNTIME_METADATA = RUNTIME_STATE
    HISTORICAL_INFERENCE = ORCHESTRATOR_METADATA
    LLM_INTERPRETATION = LLM_INFERENCE

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
    OPEN = "OPEN"
    SUPPORTED = "SUPPORTED"
    WEAKENED = "WEAKENED"
    DISPROVEN = "DISPROVEN"
    PROBABLE = "PROBABLE"
    PROVEN = "PROVEN"

    # Compatibility aliases for reports created before the trust-core release.
    PROPOSED = OPEN
    REJECTED = DISPROVEN
    INSUFFICIENT_EVIDENCE = OPEN


class DiagnosticLayer(str, Enum):
    INFRASTRUCTURE = "L0_INFRASTRUCTURE"
    ORCHESTRATOR_LIFECYCLE = "L1_ORCHESTRATOR_LIFECYCLE"
    TASK_RUNTIME = "L2_TASK_RUNTIME"
    APPLICATION_CODE = "L3_APPLICATION_OPERATOR_CODE"
    SOURCE_CONNECTIVITY = "L4_SOURCE_CONNECTIVITY"
    EXTRACTION = "L5_EXTRACTION"
    TRANSFORMATION = "L6_TRANSFORMATION"
    TARGET_LOAD = "L7_TARGET_LOAD"
    DATA_QUALITY = "L8_DATA_QUALITY"
    RECONCILIATION = "L9_RECONCILIATION"
    CONSUMPTION = "L10_CONSUMPTION"
    CERTIFICATION = "L11_CERTIFICATION"


class FindingClassification(str, Enum):
    PRIMARY_ROOT_CAUSE = "PRIMARY_ROOT_CAUSE"
    PROBABLE_ROOT_CAUSE = "PROBABLE_ROOT_CAUSE"
    CONTRIBUTING_FACTOR = "CONTRIBUTING_FACTOR"
    SECONDARY_FINDING = "SECONDARY_FINDING"
    LATENT_DEFECT = "LATENT_DEFECT"
    CONSEQUENCE = "CONSEQUENCE"
    UNRELATED_FINDING = "UNRELATED_FINDING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExecutionLifecycleEvidence:
    task_id: str
    run_id: str
    dag_id: str | None = None
    created_at: str | None = None
    scheduled_at: str | None = None
    queued_at: str | None = None
    executor_accepted_at: str | None = None
    process_created_at: str | None = None
    running_at: str | None = None
    operator_started_at: str | None = None
    first_external_call_at: str | None = None
    ended_at: str | None = None
    metadata_state: str | None = None
    executor_state: str | None = None
    task_log_exists: bool | None = None
    operator_start_proven: bool = False
    runtime_start_proven: bool = False
    try_number: int | None = None
    mapped_task_index: int | None = None
    pool: str | None = None
    queue: str | None = None
    priority: int | None = None
    executor: str | None = None
    parallelism: int | None = None
    queued_duration_seconds: float | None = None
    evidence_ids: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FirstDivergence:
    layer: DiagnosticLayer
    component: str
    expected_state: str
    observed_state: str
    occurred_at: str | None
    evidence_ids: tuple[str, ...]
    confidence: float
    proven: bool

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["layer"] = self.layer.value
        return value


@dataclass(frozen=True)
class Finding:
    title: str
    description: str
    classification: FindingClassification
    domain: str
    confidence: float
    evidence_ids: tuple[str, ...] = ()
    relationship: str = ""
    finding_id: str = field(default_factory=lambda: new_id("finding"))
    created_at: str = field(default_factory=utc_now)

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value["classification"] = self.classification.value
        return value


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
class AgentTelemetry:
    provider: str = "deterministic"
    model: str = "domain-service"
    prompt_version: str = "deterministic-v1"
    input_tokens: int = 0
    output_tokens: int = 0
    tool_call_count: int = 0
    duration_ms: float = 0.0
    retries: int = 0
    cost_usd: float = 0.0
    evidence_generated: int = 0
    handoffs: tuple[str, ...] = ()
    invocation_id: str = field(default_factory=lambda: new_id("agent_invocation"))


@dataclass(frozen=True)
class EvidenceRecord:
    kind: str
    source: str
    summary: str
    payload: dict[str, Any]
    tier: EvidenceTier = EvidenceTier.DIRECT_MEASUREMENT
    correlation: dict[str, Any] = field(default_factory=dict)
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
    domain: str = "unknown"
    prerequisites_to_prove: tuple[str, ...] = ()
    prerequisites_to_disprove: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

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
    telemetry: AgentTelemetry = field(default_factory=AgentTelemetry)
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
    question: str = ""
    structured_first_divergence: FirstDivergence | None = None
    execution_lifecycles: tuple[ExecutionLifecycleEvidence, ...] = ()
    findings: tuple[Finding, ...] = ()

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
            "question": self.question,
            "structured_first_divergence": (
                self.structured_first_divergence.public() if self.structured_first_divergence else None
            ),
            "execution_lifecycles": [item.public() for item in self.execution_lifecycles],
            "findings": [item.public() for item in self.findings],
        }
