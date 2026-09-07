from datetime import datetime

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Business concepts / contracts
# ---------------------------------------------------------------------------


class BusinessConceptCreate(BaseModel):
    name: str
    domain: str | None = None
    definition: str
    criticality: str = "TIER_2"
    owner: str | None = None


class BusinessConceptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    domain: str | None = None
    definition: str
    criticality: str
    owner: str | None = None
    created_at: datetime


class QualityContractCreate(BaseModel):
    business_concept_id: str | None = None
    dataset_ref: str
    sla_ready_by: str | None = None
    tolerance_percentage: float | None = None
    owner: str | None = None


class QualityContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    business_concept_id: str | None = None
    dataset_ref: str
    version: int
    status: str
    sla_ready_by: str | None = None
    tolerance_percentage: float | None = None
    owner: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Quality rules
# ---------------------------------------------------------------------------


class QualityRuleCreate(BaseModel):
    contract_id: str | None = None
    dbt_project_id: str | None = None
    name: str
    dimension: str
    rule_type: str
    target_table: str
    target_column: str | None = None
    expression: dict = {}
    tolerance_type: str | None = None
    tolerance_value: float | None = None
    severity: str = "P2"


class QualityRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    contract_id: str | None = None
    dbt_project_id: str | None = None
    name: str
    dimension: str
    rule_type: str
    target_table: str
    target_column: str | None = None
    expression: dict
    tolerance_type: str | None = None
    tolerance_value: float | None = None
    severity: str
    status: str
    created_at: datetime


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    evidence_type: str
    source_type: str
    dataset_ref: str
    value: str | None = None
    query_text: str | None = None
    observed_at: datetime


class QualityRuleRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    quality_rule_id: str
    status: str
    measured_value: float | None = None
    compiled_sql: str | None = None
    dialect: str | None = None
    message: str | None = None
    executed_at: datetime
    evidence: list[EvidenceOut] = []


class CompiledRuleOut(BaseModel):
    dialect: str
    sql: str


# ---------------------------------------------------------------------------
# Incidents, remediation, certification
# ---------------------------------------------------------------------------


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    quality_rule_id: str | None = None
    severity: str
    status: str
    dataset_ref: str
    title: str
    description: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class CertificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    dataset_ref: str
    dbt_project_id: str | None = None
    contract_id: str | None = None
    status: str
    reason: str
    evaluated_at: datetime


# ---------------------------------------------------------------------------
# RCA / claims / remediation
# ---------------------------------------------------------------------------


class ClaimEvidenceLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    relationship_type: str
    evidence: EvidenceOut


class AgentClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    incident_id: str | None = None
    claim_type: str
    statement: str
    status: str
    generated_by: str
    created_at: datetime
    evidence_links: list[ClaimEvidenceLinkOut] = []


class RemediationProposalCreate(BaseModel):
    claim_id: str
    target_file: str  # path relative to the dbt project's project_dir
    find_text: str
    replace_text: str


class RemediationProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    claim_id: str
    target_file: str | None = None
    proposed_change: str
    status: str
    created_at: datetime
    applied_at: datetime | None = None
