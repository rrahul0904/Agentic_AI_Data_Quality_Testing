"""Domain model for the Agentic AI Data Quality & Pipeline Assurance layer
(Horizon A slice). Extends the existing v0.2 project/job/DAG models rather
than replacing them -- a QualityRule targets a DbtProject; a QualityRuleRun
may optionally belong to a TestRun so quality-rule evidence sits alongside
dbt/Airflow evidence for the same run.

Schema is written to be PostgreSQL-compatible (no SQLite-specific types)
even though SQLite is still the runtime database for this phase, per the
master implementation prompt's migration guidance.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Business Context Intelligence (slice)
# ---------------------------------------------------------------------------


class BusinessConcept(Base):
    __tablename__ = "business_concepts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    definition: Mapped[str] = mapped_column(Text)
    criticality: Mapped[str] = mapped_column(String, default="TIER_2")  # TIER_1 | TIER_2 | TIER_3
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    contracts: Mapped[list["QualityContract"]] = relationship(back_populates="business_concept")


class QualityContract(Base):
    """A versioned, owned quality contract for one dataset, derived from a
    business concept. See docs/ARCHITECTURE.md for the business-language ->
    contract conversion this models."""

    __tablename__ = "quality_contracts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    business_concept_id: Mapped[str | None] = mapped_column(ForeignKey("business_concepts.id"), nullable=True)

    dataset_ref: Mapped[str] = mapped_column(String)  # e.g. "dbt_project:<id>:fct_orders"
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String, default="DRAFT")  # DRAFT | APPROVED | DEPRECATED
    sla_ready_by: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "06:00"
    tolerance_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    business_concept: Mapped[BusinessConcept | None] = relationship(back_populates="contracts")
    rules: Mapped[list["QualityRule"]] = relationship(back_populates="contract")


# ---------------------------------------------------------------------------
# Quality Rule Engine
# ---------------------------------------------------------------------------

RULE_DIMENSIONS = (
    "schema", "completeness", "uniqueness", "validity", "accuracy", "consistency",
    "referential_integrity", "freshness", "volume", "distribution", "anomaly",
    "transformation", "pipeline", "business_rule",
)

RULE_TYPES = (
    "not_null", "unique", "accepted_values", "row_count_reconciliation",
    "aggregate_reconciliation", "custom_sql",
)


class QualityRule(Base):
    """Canonical, platform-independent quality rule. `expression` carries
    rule-type-specific parameters (e.g. {"values": [...]} for accepted_values,
    {"source_dataset_ref": ..., "column": "amount"} for aggregate
    reconciliation) so this one table covers every rule type in the taxonomy
    without a rule-type-specific table per dimension."""

    __tablename__ = "quality_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("quality_contracts.id"), nullable=True)
    dbt_project_id: Mapped[str | None] = mapped_column(ForeignKey("dbt_projects.id"), nullable=True)

    name: Mapped[str] = mapped_column(String)
    dimension: Mapped[str] = mapped_column(String)  # one of RULE_DIMENSIONS
    rule_type: Mapped[str] = mapped_column(String)  # one of RULE_TYPES
    target_table: Mapped[str] = mapped_column(String)
    target_column: Mapped[str | None] = mapped_column(String, nullable=True)
    expression: Mapped[dict] = mapped_column(JSON, default=dict)
    tolerance_type: Mapped[str | None] = mapped_column(String, nullable=True)  # percentage | absolute
    tolerance_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String, default="P2")  # P1 | P2 | P3
    status: Mapped[str] = mapped_column(String, default="ACTIVE")  # ACTIVE | DISABLED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    contract: Mapped[QualityContract | None] = relationship(back_populates="rules")
    runs: Mapped[list["QualityRuleRun"]] = relationship(back_populates="rule", cascade="all, delete-orphan")


class QualityRuleRun(Base):
    """One execution of one QualityRule -- the deterministic pass/fail record.
    Optionally attached to a TestRun so quality-rule evidence sits next to
    dbt/Airflow evidence for the same overall run."""

    __tablename__ = "quality_rule_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    quality_rule_id: Mapped[str] = mapped_column(ForeignKey("quality_rules.id"))
    test_run_id: Mapped[str | None] = mapped_column(ForeignKey("test_runs.id"), nullable=True)

    status: Mapped[str] = mapped_column(String, default="RUNNING")  # PASS | FAIL | ERROR
    measured_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    compiled_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialect: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    rule: Mapped[QualityRule] = relationship(back_populates="runs")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="rule_run", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Evidence Intelligence (slice)
# ---------------------------------------------------------------------------

EVIDENCE_TYPES = (
    "ROW_COUNT", "AGGREGATE", "HASH", "SCHEMA", "QUERY_RESULT",
    "DBT_STATE", "AIRFLOW_STATE", "CODE_DIFF", "CONTRACT",
)


class Evidence(Base):
    """A single, typed, provenance-carrying fact. Deliberately small/scalar
    (a value, not a dataset) -- large results belong in the existing
    Artifact table (raw JSON blobs), not here, per the "small evidence to
    the relational store, large artifacts to object storage" principle."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    quality_rule_run_id: Mapped[str | None] = mapped_column(ForeignKey("quality_rule_runs.id"), nullable=True)

    evidence_type: Mapped[str] = mapped_column(String)  # one of EVIDENCE_TYPES
    source_type: Mapped[str] = mapped_column(String)  # duckdb | snowflake | dbt | airflow | business
    dataset_ref: Mapped[str] = mapped_column(String)
    value: Mapped[str | None] = mapped_column(String, nullable=True)  # stringified scalar
    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)

    rule_run: Mapped[QualityRuleRun | None] = relationship(back_populates="evidence")


# ---------------------------------------------------------------------------
# Claim-Evidence Grounding Gateway
# ---------------------------------------------------------------------------

CLAIM_STATUSES = ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNVERIFIED", "CONFLICTED", "REJECTED", "UNKNOWN")
CLAIM_TYPES = ("RCA", "QUALITY_INTENT", "MAPPING", "IMPACT", "REMEDIATION")


class AgentClaim(Base):
    """An agent's conclusion. Never trusted on its own -- status is computed
    by the Grounding Gateway (services/grounding.py) from linked evidence,
    not asserted by the agent/LLM itself."""

    __tablename__ = "agent_claims"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)

    claim_type: Mapped[str] = mapped_column(String)  # one of CLAIM_TYPES
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="UNKNOWN")  # one of CLAIM_STATUSES
    generated_by: Mapped[str] = mapped_column(String)  # agent name
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    incident: Mapped["Incident | None"] = relationship(back_populates="claims")
    evidence_links: Mapped[list["ClaimEvidenceLink"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    remediation_proposals: Mapped[list["RemediationProposal"]] = relationship(back_populates="claim")
    llm_calls: Mapped[list["LLMCallLog"]] = relationship(back_populates="agent_claim")


class LLMCallLog(Base):
    """AI cost accounting (Architecture spec Section 30.2) -- one row per
    LLM Gateway call. Kept even when a call contributes nothing usable, so
    token spend is never invisible."""

    __tablename__ = "llm_call_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    agent_claim_id: Mapped[str | None] = mapped_column(ForeignKey("agent_claims.id"), nullable=True)

    purpose: Mapped[str] = mapped_column(String)  # e.g. "rca_ambiguous_upstream"
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    tokens_in: Mapped[int | None] = mapped_column(nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    agent_claim: Mapped[AgentClaim | None] = relationship(back_populates="llm_calls")


class ClaimEvidenceLink(Base):
    __tablename__ = "claim_evidence_links"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("agent_claims.id"))
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    relationship_type: Mapped[str] = mapped_column(String)  # SUPPORTING | CONTRADICTORY

    claim: Mapped[AgentClaim] = relationship(back_populates="evidence_links")
    evidence: Mapped["Evidence"] = relationship()


# ---------------------------------------------------------------------------
# Incidents, remediation, certification
# ---------------------------------------------------------------------------


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    quality_rule_id: Mapped[str | None] = mapped_column(ForeignKey("quality_rules.id"), nullable=True)

    severity: Mapped[str] = mapped_column(String, default="P2")
    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN | INVESTIGATING | RESOLVED
    dataset_ref: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    claims: Mapped[list[AgentClaim]] = relationship(back_populates="incident")


class RemediationProposal(Base):
    __tablename__ = "remediation_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("agent_claims.id"))

    target_file: Mapped[str | None] = mapped_column(String, nullable=True)
    proposed_change: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="PROPOSED")  # PROPOSED | APPROVED | APPLIED | REJECTED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    claim: Mapped[AgentClaim] = relationship(back_populates="remediation_proposals")


class Certification(Base):
    """Derived, explainable status for a dataset -- never an arbitrary AI
    score. `reason` records exactly which rules/evidence produced the
    status (see services/certification.py)."""

    __tablename__ = "certifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    dataset_ref: Mapped[str] = mapped_column(String)
    dbt_project_id: Mapped[str | None] = mapped_column(ForeignKey("dbt_projects.id"), nullable=True)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("quality_contracts.id"), nullable=True)

    status: Mapped[str] = mapped_column(String, default="UNKNOWN")  # CERTIFIED | AT_RISK | FAILED | UNKNOWN
    reason: Mapped[str] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
