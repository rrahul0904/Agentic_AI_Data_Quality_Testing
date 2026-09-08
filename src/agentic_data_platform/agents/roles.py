from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agentic_data_platform.agents.contracts import (
    AgentHypothesis,
    AgentPolicy,
    AgentResult,
    AgentRole,
    EvidenceRecord,
    EvidenceTier,
    HypothesisStatus,
    RemediationPlan,
)
from agentic_data_platform.agents.scenarios import FailureScenario


ToolInvoker = Callable[[AgentRole, str, dict[str, Any]], dict[str, Any]]


@dataclass
class AgentContext:
    scenario: FailureScenario
    incident_id: str
    project: Path
    invoke: ToolInvoker
    evidence: list[EvidenceRecord]
    shared: dict[str, Any]

    def tool(self, role: AgentRole, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return self.invoke(role, name, args)


class BaseSpecialistAgent:
    role: AgentRole
    policy: AgentPolicy

    def result(
        self,
        *,
        status: str,
        claim: str,
        confidence: float,
        context: AgentContext,
        reasoning: str,
        next_action: str,
        observations: dict[str, Any] | None = None,
        tools: tuple[str, ...] = (),
        evidence_ids: tuple[str, ...] = (),
        contradictory_ids: tuple[str, ...] = (),
        assets: tuple[str, ...] | None = None,
    ) -> AgentResult:
        return AgentResult(
            role=self.role,
            status=status,
            claim=claim,
            confidence=max(0.0, min(1.0, confidence)),
            supporting_evidence_ids=evidence_ids,
            contradictory_evidence_ids=contradictory_ids,
            source_systems=context.scenario.source_systems,
            affected_assets=assets if assets is not None else (context.scenario.affected_asset,),
            reasoning_summary=reasoning,
            next_recommended_action=next_action,
            observations=observations or {},
            tools_used=tools,
        )


class MetadataAgent(BaseSpecialistAgent):
    role = AgentRole.METADATA
    policy = AgentPolicy(("platform_graph", "airflow_inventory", "dbt_manifest_summary", "dbt_incremental_analysis"))

    def run(self, context: AgentContext) -> AgentResult:
        used = []
        observations: dict[str, Any] = {
            "pipeline_path": list(context.scenario.pipeline_path),
            "affected_asset": context.scenario.affected_asset,
        }
        for name, args in (
            ("platform_graph", {"project": str(context.project)}),
            ("airflow_inventory", {"project": str(context.project)}),
            ("dbt_manifest_summary", {"project": str(context.project)}),
            ("dbt_incremental_analysis", {"project": str(context.project)}),
        ):
            try:
                value = context.tool(self.role, name, args)
                used.append(name)
                if name == "platform_graph":
                    observations["graph"] = {
                        "node_count": value.get("node_count"),
                        "edge_count": value.get("edge_count"),
                        "node_types": value.get("node_types"),
                    }
                elif name == "airflow_inventory":
                    observations["airflow_dag_count"] = value.get("dag_count")
                elif name == "dbt_manifest_summary":
                    observations["dbt"] = value
                else:
                    observations["incremental"] = value
            except (KeyError, ValueError, FileNotFoundError) as exc:
                observations[f"{name}_error"] = str(exc)
        return self.result(
            status="PASS",
            claim="Platform metadata context resolved without inventing external runtime state.",
            confidence=0.98,
            context=context,
            reasoning="Repository, Airflow AST, and dbt artifact metadata establish the technical context for the incident.",
            next_action="Use lineage and business context to narrow the causal path.",
            observations=observations,
            tools=tuple(used),
        )


class BusinessContextAgent(BaseSpecialistAgent):
    role = AgentRole.BUSINESS_CONTEXT
    policy = AgentPolicy()

    _CONCEPTS = {
        "payment": {"metrics": ["payment completeness", "gross revenue", "net revenue"], "criticality": "P1"},
        "reservation": {"metrics": ["reservation volume", "occupancy", "ADR", "RevPAR"], "criticality": "P1"},
        "revenue": {"metrics": ["gross revenue", "net revenue", "ADR", "RevPAR"], "criticality": "P1"},
        "booking": {"metrics": ["booking conversion", "confirmation rate"], "criticality": "P1"},
        "customer": {"metrics": ["guest coverage", "identity resolution"], "criticality": "P2"},
    }

    def run(self, context: AgentContext) -> AgentResult:
        concept = self._CONCEPTS.get(context.scenario.business_concept, {"metrics": [], "criticality": "P2"})
        context.shared["business_context"] = concept
        return self.result(
            status="PASS",
            claim=f"{context.scenario.business_concept} incident affects business correctness even if orchestration is technically green.",
            confidence=0.96,
            context=context,
            reasoning="Business quality is evaluated from measured domain metrics independently of Airflow/dbt task status.",
            next_action="Evaluate business-aware quality signals and determine whether an incident is warranted.",
            observations=concept,
        )


class LineageAgent(BaseSpecialistAgent):
    role = AgentRole.LINEAGE
    policy = AgentPolicy(("platform_lineage", "platform_impact"))

    def run(self, context: AgentContext) -> AgentResult:
        observations = {"canonical_path": list(context.scenario.pipeline_path)}
        tools: list[str] = []
        try:
            lineage = context.tool(
                self.role,
                "platform_lineage",
                {"project": str(context.project), "node": context.scenario.affected_asset, "depth": 12},
            )
            observations["repository_lineage"] = lineage
            tools.append("platform_lineage")
        except (KeyError, ValueError, FileNotFoundError) as exc:
            observations["repository_lineage_unavailable"] = str(exc)
        return self.result(
            status="PASS",
            claim="Cross-system causal path identified from source through orchestration, warehouse, and dbt assets.",
            confidence=0.97,
            context=context,
            reasoning="The scenario mapping is reconciled with repository lineage where a resolvable asset exists.",
            next_action="Use the causal path to compare adjacent stages and localize the first divergence.",
            observations=observations,
            tools=tuple(tools),
            assets=tuple(context.scenario.pipeline_path),
        )


class TransformationAgent(BaseSpecialistAgent):
    role = AgentRole.TRANSFORMATION
    policy = AgentPolicy(("dbt_compiled_sql_review", "dbt_incremental_analysis"))

    def run(self, context: AgentContext) -> AgentResult:
        signals = context.scenario.signals
        findings = []
        if signals.get("filter_expression"):
            findings.append({"kind": "filter", "expression": signals["filter_expression"], "risk": "row_exclusion"})
        if signals.get("join_cardinality") == "many_to_many":
            findings.append({"kind": "join", "risk": "fanout", "duplicate_business_keys": signals.get("duplicate_business_keys", 0)})
        if signals.get("late_arriving_rows"):
            findings.append({
                "kind": "incremental_predicate",
                "lookback_hours": signals.get("incremental_lookback_hours"),
                "max_late_hours": signals.get("max_late_hours"),
                "risk": "late_arriving_data_loss",
            })
        if signals.get("compile_error"):
            findings.append({"kind": "compile", "error": signals["compile_error"]})
        tools: list[str] = []
        try:
            context.tool(self.role, "dbt_incremental_analysis", {"project": str(context.project)})
            tools.append("dbt_incremental_analysis")
        except (KeyError, ValueError, FileNotFoundError):
            pass
        return self.result(
            status="WARN" if findings else "PASS",
            claim="Transformation-specific failure modes evaluated for filters, joins, compilation, and incremental predicates.",
            confidence=0.94 if findings else 0.85,
            context=context,
            reasoning="Transformation analysis is invoked only when evidence indicates the divergence is at or downstream of dbt.",
            next_action="Feed transformation findings into RCA hypothesis evaluation.",
            observations={"findings": findings},
            tools=tuple(tools),
        )


class MappingAgent(BaseSpecialistAgent):
    role = AgentRole.MAPPING
    policy = AgentPolicy()

    def run(self, context: AgentContext) -> AgentResult:
        path = list(context.scenario.pipeline_path)
        mappings = [{"source": path[index], "target": path[index + 1]} for index in range(max(0, len(path) - 1))]
        return self.result(
            status="PASS",
            claim="Source-to-target mapping chain materialized for deterministic reconciliation.",
            confidence=0.96,
            context=context,
            reasoning="Adjacent path mappings provide explicit reconciliation boundaries instead of relying on natural-language guesses.",
            next_action="Reconcile mapped boundaries according to the execution plan.",
            observations={"mappings": mappings},
            assets=tuple(path),
        )


class QualityAgent(BaseSpecialistAgent):
    role = AgentRole.QUALITY
    policy = AgentPolicy(("reconcile_row_count", "reconcile_aggregate", "reconcile_freshness"))

    def run(self, context: AgentContext) -> AgentResult:
        signals = context.scenario.signals
        anomalies = []
        if abs(float(signals.get("payment_volume_change_pct", 0))) >= 15:
            anomalies.append({"metric": "payment_volume_change_pct", "value": signals["payment_volume_change_pct"], "threshold": 15})
        ratio = signals.get("payment_to_reservation_ratio")
        baseline = signals.get("historical_payment_to_reservation_ratio")
        if ratio is not None and baseline is not None and abs(float(ratio) - float(baseline)) >= 0.1:
            anomalies.append({"metric": "payment_to_reservation_ratio", "value": ratio, "baseline": baseline})
        if signals.get("freshness_lag_minutes", 0) > signals.get("freshness_sla_minutes", float("inf")):
            anomalies.append({"metric": "freshness_lag_minutes", "value": signals["freshness_lag_minutes"], "sla": signals["freshness_sla_minutes"]})
        if signals.get("null_spike"):
            anomalies.append({"metric": "null_percentage", "value": signals.get("current_null_pct"), "baseline": signals.get("historical_null_pct")})
        failed = [item for item in context.scenario.comparisons if item.get("status") == "FAIL"]
        anomalies.extend({"metric": "boundary_reconciliation", "pair": item["pair"], "detail": item} for item in failed)
        context.shared["anomaly"] = {
            "detected": bool(anomalies),
            "signals": anomalies,
            "airflow_state": signals.get("airflow_state"),
            "dbt_state": signals.get("dbt_state"),
        }
        return self.result(
            status="FAIL" if anomalies else "PASS",
            claim="Business/data anomaly detected independently of orchestration status." if anomalies else "No quality anomaly detected.",
            confidence=0.99 if anomalies else 0.9,
            context=context,
            reasoning="Deterministic thresholds and source/target reconciliation drive the incident signal; no LLM determines PASS/FAIL.",
            next_action="Open or continue an incident and collect bounded evidence." if anomalies else "Continue normal certification.",
            observations=context.shared["anomaly"],
        )


class ExecutionPlanningAgent(BaseSpecialistAgent):
    role = AgentRole.EXECUTION_PLANNING
    policy = AgentPolicy()

    def run(self, context: AgentContext) -> AgentResult:
        comparisons = list(context.scenario.comparisons)
        strategy = "aggregate_reconciliation"
        if any("source_count" in item for item in comparisons):
            strategy = "bounded_row_count_reconciliation"
        if context.scenario.signals.get("cdc_gap"):
            strategy = "incremental_sequence_reconciliation"
        if context.scenario.signals.get("schema_drift"):
            strategy = "metadata_only_schema_comparison"
        plan = {
            "strategy": strategy,
            "comparisons": comparisons,
            "maximum_exception_rows": 1000,
            "full_scan": False,
            "estimated_cost": "bounded/local fixture; warehouse estimator required for live mode",
            "timeout_seconds": 120,
            "fallback": "bucket_hash_then_exception_keys",
            "approval_required": False,
        }
        context.shared["execution_plan"] = plan
        return self.result(
            status="PASS",
            claim=f"Bounded investigation plan selected: {strategy}.",
            confidence=0.97,
            context=context,
            reasoning="The planner chooses the cheapest deterministic strategy that can prove or reject the current hypotheses.",
            next_action="Collect immutable evidence for each planned comparison.",
            observations=plan,
        )


class EvidenceAgent(BaseSpecialistAgent):
    role = AgentRole.EVIDENCE
    policy = AgentPolicy()

    def run(self, context: AgentContext) -> tuple[AgentResult, list[EvidenceRecord]]:
        records: list[EvidenceRecord] = []
        correlation = {
            "incident_id": context.incident_id,
            "batch_id": context.scenario.signals.get("batch_id") or f"{context.scenario.scenario_id}-batch",
            "airflow_run_id": context.scenario.signals.get("airflow_run_id") or f"proving-ground::{context.scenario.scenario_id}",
            "logical_date": context.scenario.signals.get("logical_date"),
            "source_watermark": context.scenario.signals.get("persisted_watermark"),
            "snowflake_query_id": context.scenario.signals.get("snowflake_query_id"),
            "dbt_invocation_id": context.scenario.signals.get("dbt_invocation_id") or f"proving-ground::{context.scenario.scenario_id}",
            "git_sha": context.scenario.signals.get("git_sha"),
            "quality_run": context.scenario.signals.get("quality_run") or context.incident_id,
            "certification": "FAILED",
        }
        for item in context.scenario.comparisons:
            records.append(EvidenceRecord(
                kind="reconciliation",
                source=item["pair"],
                summary=f"{item['pair']} reconciliation {item['status']}",
                payload=dict(item),
                tier=EvidenceTier.DIRECT_MEASUREMENT,
                correlation=correlation,
            ))
        records.append(EvidenceRecord(
            kind="runtime_state",
            source="airflow/dbt",
            summary="Captured orchestration states and failure signals.",
            payload=dict(context.scenario.signals),
            tier=EvidenceTier.RUNTIME_METADATA,
            correlation=correlation,
        ))
        context.evidence.extend(records)
        result = self.result(
            status="PASS",
            claim=f"Collected {len(records)} immutable evidence records with provenance tiers.",
            confidence=0.99,
            context=context,
            reasoning="Direct measurements and runtime metadata are persisted before RCA and outrank later interpretation.",
            next_action="Localize first divergence and evaluate competing RCA hypotheses.",
            evidence_ids=tuple(item.evidence_id for item in records),
            observations={"evidence_count": len(records), "tiers": sorted({item.tier.label for item in records})},
        )
        return result, records


def first_divergence(comparisons: tuple[dict[str, Any], ...]) -> str | None:
    for item in comparisons:
        if str(item.get("status")).upper() == "FAIL":
            return str(item.get("pair"))
    return None


class RCAAgent(BaseSpecialistAgent):
    role = AgentRole.RCA
    policy = AgentPolicy()

    _HYPOTHESES = (
        ("WATERMARK_ADVANCED_BEYOND_EXTRACT", "Persisted watermark advanced beyond the last successfully extracted record."),
        ("DBT_FILTER_EXCLUDES_VALID_STATUS", "A dbt filter excludes valid business-status rows."),
        ("DBT_JOIN_FANOUT", "A many-to-many join duplicates the business grain."),
        ("DBT_INCREMENTAL_LATE_ARRIVAL_GAP", "The incremental lookback misses late-arriving rows."),
        ("AIRFLOW_RETRY_DUPLICATE_LOAD", "An Airflow retry reloaded an already committed batch."),
        ("SNOWFLAKE_PERMISSION_DENIED", "Snowflake rejected the load because the runtime role lacks privileges."),
        ("SNOWFLAKE_PARTIAL_LOAD", "The warehouse load omitted one or more extracted files/rows."),
        ("SOURCE_SCHEMA_DRIFT", "Source schema changed incompatibly with the target contract."),
        ("SOURCE_FRESHNESS_BREACH", "The upstream source is stale relative to its SLA."),
        ("SOURCE_NULL_SPIKE", "A source/domain field has an abnormal null-rate increase."),
        ("REVENUE_TRANSFORMATION_MISMATCH", "A downstream transformation changes the certified revenue metric."),
        ("MISSING_CUSTOMER_REFERENCE", "Required parent/customer keys are absent."),
        ("CDC_EVENT_GAP", "The CDC sequence contains a missing range."),
        ("OUT_OF_ORDER_EVENT", "Out-of-order events overwrote or bypassed the correct current state."),
        ("DBT_TEST_FAILURE", "A dbt assertion detected a deterministic model-grain failure."),
        ("DBT_COMPILATION_FAILURE", "dbt compilation failed before data execution."),
        ("AIRFLOW_TASK_FAILURE", "An Airflow task failed at runtime."),
        ("BUSINESS_COMPLETENESS_ANOMALY", "Business completeness degraded while orchestration remained green."),
    )

    def _supported_name(self, context: AgentContext) -> str:
        s = context.scenario.signals
        failed_pair = first_divergence(context.scenario.comparisons) or ""
        if s.get("warehouse_error") and "privilege" in str(s["warehouse_error"]).casefold():
            return "SNOWFLAKE_PERMISSION_DENIED"
        if s.get("compile_error"):
            return "DBT_COMPILATION_FAILURE"
        if s.get("task_state") == "FAILED":
            return "AIRFLOW_TASK_FAILURE"
        if s.get("schema_drift"):
            return "SOURCE_SCHEMA_DRIFT"
        if s.get("cdc_gap"):
            return "CDC_EVENT_GAP"
        if s.get("out_of_order_events"):
            return "OUT_OF_ORDER_EVENT"
        if s.get("null_spike"):
            return "SOURCE_NULL_SPIKE"
        if s.get("freshness_lag_minutes", 0) > s.get("freshness_sla_minutes", float("inf")):
            return "SOURCE_FRESHNESS_BREACH"
        if s.get("filter_expression") and s.get("valid_status_missing"):
            return "DBT_FILTER_EXCLUDES_VALID_STATUS"
        if s.get("join_cardinality") == "many_to_many":
            return "DBT_JOIN_FANOUT"
        if s.get("late_arriving_rows", 0) and s.get("max_late_hours", 0) > s.get("incremental_lookback_hours", 0):
            return "DBT_INCREMENTAL_LATE_ARRIVAL_GAP"
        if s.get("task_try_number", 0) > 1 and s.get("duplicate_business_keys", 0):
            return "AIRFLOW_RETRY_DUPLICATE_LOAD"
        if s.get("manifest_files", 0) > s.get("loaded_files", 0):
            return "SNOWFLAKE_PARTIAL_LOAD"
        if s.get("orphan_guest_keys", 0):
            return "MISSING_CUSTOMER_REFERENCE"
        if s.get("dbt_test_name") and s.get("failing_rows", 0):
            return "DBT_TEST_FAILURE"
        if s.get("revenue_variance", 0):
            return "REVENUE_TRANSFORMATION_MISMATCH"
        if s.get("persisted_watermark") and s.get("extracted_max_timestamp") and s["persisted_watermark"] > s["extracted_max_timestamp"]:
            return "WATERMARK_ADVANCED_BEYOND_EXTRACT"
        if (
            s.get("airflow_state") == "SUCCESS"
            and s.get("dbt_state") == "SUCCESS"
            and abs(float(s.get("payment_volume_change_pct", 0))) >= 15
        ):
            return "BUSINESS_COMPLETENESS_ANOMALY"
        if failed_pair == "source→raw":
            return "BUSINESS_COMPLETENESS_ANOMALY"
        return "INSUFFICIENT_EVIDENCE"

    def run(self, context: AgentContext) -> tuple[AgentResult, list[AgentHypothesis]]:
        supported_name = self._supported_name(context)
        evidence_ids = tuple(item.evidence_id for item in context.evidence)
        hypotheses: list[AgentHypothesis] = []
        for name, statement in self._HYPOTHESES:
            status = HypothesisStatus.SUPPORTED if name == supported_name else HypothesisStatus.REJECTED
            hypotheses.append(AgentHypothesis(
                name,
                statement,
                status,
                0.96 if status is HypothesisStatus.SUPPORTED else 0.03,
                evidence_ids if status is HypothesisStatus.SUPPORTED else (),
                () if status is HypothesisStatus.SUPPORTED else evidence_ids[:1],
            ))
        context.shared["root_cause"] = supported_name
        context.shared["first_divergence"] = first_divergence(context.scenario.comparisons)
        result = self.result(
            status="DIAGNOSED" if supported_name != "INSUFFICIENT_EVIDENCE" else "UNVERIFIED",
            claim=supported_name,
            confidence=0.96 if supported_name != "INSUFFICIENT_EVIDENCE" else 0.0,
            context=context,
            reasoning="Competing hypotheses are evaluated against direct reconciliation and runtime signals; rejected candidates remain auditable.",
            next_action="Calculate downstream blast radius before proposing any mutation.",
            evidence_ids=evidence_ids,
            observations={
                "first_divergence": context.shared["first_divergence"],
                "supported_hypothesis": supported_name,
                "hypothesis_count": len(hypotheses),
            },
        )
        return result, hypotheses


class ImpactAgent(BaseSpecialistAgent):
    role = AgentRole.IMPACT
    policy = AgentPolicy(("platform_impact",))

    def run(self, context: AgentContext) -> AgentResult:
        assets = list(context.scenario.downstream_assets)
        tools: list[str] = []
        try:
            impact = context.tool(
                self.role,
                "platform_impact",
                {"project": str(context.project), "node": context.scenario.affected_asset, "depth": 12},
            )
            tools.append("platform_impact")
            for item in impact.get("downstream", []):
                name = item.get("name")
                if name and name not in assets:
                    assets.append(name)
        except (KeyError, ValueError, FileNotFoundError):
            pass
        business = context.shared.get("business_context", {})
        context.shared["blast_radius"] = assets
        return self.result(
            status="PASS",
            claim=f"Blast radius contains {len(assets)} downstream assets.",
            confidence=0.94,
            context=context,
            reasoning="Downstream graph traversal is combined with scenario-specific business dependency metadata.",
            next_action="Generate the minimum-risk remediation and rollback plan.",
            observations={"downstream_assets": assets, "business_metrics": business.get("metrics", []), "criticality": business.get("criticality", "P2")},
            tools=tuple(tools),
            assets=tuple(assets) or (context.scenario.affected_asset,),
        )


class RemediationAgent(BaseSpecialistAgent):
    role = AgentRole.REMEDIATION
    policy = AgentPolicy()

    def run(self, context: AgentContext) -> tuple[AgentResult, RemediationPlan]:
        evidence_ids = tuple(item.evidence_id for item in context.evidence)
        blast = tuple(context.shared.get("blast_radius", ()))
        action = context.scenario.remediation_action
        plan = RemediationPlan(
            action=action,
            reason=f"Evidence-supported root cause: {context.shared.get('root_cause')}",
            evidence_ids=evidence_ids,
            risk="MEDIUM",
            blast_radius=blast,
            rollback="Restore the pre-remediation watermark/code/data snapshot and stop selective reruns.",
            verification_plan=(
                "rerun original failing check",
                "rerun first-divergence reconciliation",
                "run impacted dbt tests",
                "confirm business metric",
                "re-certify impacted assets",
            ),
            requires_approval=True,
            arguments={"scenario_id": context.scenario.scenario_id, "bounded": True},
        )
        result = self.result(
            status="PROPOSED",
            claim=f"Proposed remediation {action}; no mutation has executed.",
            confidence=0.95,
            context=context,
            reasoning="The proposed action is scoped to the first divergence and impact graph, with an explicit rollback and verification plan.",
            next_action="Require explicit human approval before executing the remediation.",
            evidence_ids=evidence_ids,
            observations={"plan_id": plan.plan_id, "risk": plan.risk, "requires_approval": True},
            assets=blast or (context.scenario.affected_asset,),
        )
        return result, plan


SPECIALIST_AGENTS = {
    AgentRole.METADATA: MetadataAgent(),
    AgentRole.BUSINESS_CONTEXT: BusinessContextAgent(),
    AgentRole.LINEAGE: LineageAgent(),
    AgentRole.TRANSFORMATION: TransformationAgent(),
    AgentRole.MAPPING: MappingAgent(),
    AgentRole.QUALITY: QualityAgent(),
    AgentRole.EXECUTION_PLANNING: ExecutionPlanningAgent(),
    AgentRole.EVIDENCE: EvidenceAgent(),
    AgentRole.RCA: RCAAgent(),
    AgentRole.IMPACT: ImpactAgent(),
    AgentRole.REMEDIATION: RemediationAgent(),
}


def agent_roster() -> list[dict[str, Any]]:
    supervisor = {
        "role": AgentRole.SUPERVISOR.value,
        "identity": "Supervisor Agent",
        "responsibility": "Dynamic investigation planning, delegation, approval routing, verification and closure.",
        "policy": AgentPolicy(("platform_graph", "platform_lineage", "platform_impact")).__dict__,
    }
    specialists = []
    for role, agent in SPECIALIST_AGENTS.items():
        specialists.append({
            "role": role.value,
            "identity": role.value.replace("_", " ").title() + " Agent",
            "responsibility": agent.__class__.__doc__ or agent.__class__.__name__,
            "policy": agent.policy.__dict__,
        })
    return [supervisor, *specialists]
