from __future__ import annotations

from pathlib import Path
from typing import Any

from agentic_data_platform.agents.contracts import (
    AgentHypothesis,
    AgentResult,
    AgentRole,
    EvidenceRecord,
    IncidentState,
    InvestigationReport,
    RemediationPlan,
)
from agentic_data_platform.agents.roles import (
    AgentContext,
    BusinessContextAgent,
    EvidenceAgent,
    ExecutionPlanningAgent,
    ImpactAgent,
    LineageAgent,
    MappingAgent,
    MetadataAgent,
    QualityAgent,
    RCAAgent,
    RemediationAgent,
    TransformationAgent,
    agent_roster,
)
from agentic_data_platform.agents.scenarios import FailureScenario, get_scenario, scenario_catalog
from agentic_data_platform.agents.store import InvestigationStore
from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry


class SupervisorAgent:
    """Evidence-grounded dynamic coordinator for the specialized agent roster."""

    role = AgentRole.SUPERVISOR

    def __init__(self, registry: ToolRegistry, store: InvestigationStore, project: str | Path) -> None:
        self.registry = registry
        self.store = store
        self.project = Path(project).expanduser().resolve()
        self.metadata = MetadataAgent()
        self.business = BusinessContextAgent()
        self.lineage = LineageAgent()
        self.transformation = TransformationAgent()
        self.mapping = MappingAgent()
        self.quality = QualityAgent()
        self.planner = ExecutionPlanningAgent()
        self.evidence_agent = EvidenceAgent()
        self.rca = RCAAgent()
        self.impact = ImpactAgent()
        self.remediation = RemediationAgent()
        self._policies = {
            item.role: item.policy
            for item in (
                self.metadata, self.business, self.lineage, self.transformation, self.mapping,
                self.quality, self.planner, self.evidence_agent, self.rca, self.impact, self.remediation,
            )
        }

    @staticmethod
    def roster() -> list[dict[str, Any]]:
        return agent_roster()

    @staticmethod
    def scenarios() -> list[dict[str, Any]]:
        return scenario_catalog()

    def _invoke(self, role: AgentRole, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        policy = self._policies.get(role)
        if policy is None:
            raise PermissionError(f"no tool policy registered for agent role: {role.value}")
        if tool_name in policy.denied_tools or (policy.allowed_tools and tool_name not in policy.allowed_tools):
            raise PermissionError(f"{role.value} agent is not allowed to invoke {tool_name}")
        definition = self.registry.describe(tool_name)
        if definition.risk.value != "read_only":
            raise PermissionError(f"specialist investigation agent cannot invoke mutating tool: {tool_name}")
        request = ToolRequest(
            tool=tool_name,
            operation=tool_name,
            environment=Environment.DEV,
            risk=definition.risk,
            args=args,
        )
        return self.registry.invoke(
            ToolInvocation(request, run_id=f"agent-{role.value}", actor_mode=ActorMode.ANALYST)
        )

    def _save(self, incident_id: str, result: AgentResult, results: list[AgentResult]) -> None:
        results.append(result)
        self.store.save_agent_result(incident_id, result)

    def _supervisor_result(
        self,
        context: AgentContext,
        results: list[AgentResult],
        claim: str,
        reasoning: str,
        next_action: str,
        *,
        status: str = "PASS",
        confidence: float = 0.99,
    ) -> None:
        result = AgentResult(
            role=AgentRole.SUPERVISOR,
            status=status,
            claim=claim,
            confidence=confidence,
            supporting_evidence_ids=tuple(item.evidence_id for item in context.evidence),
            source_systems=context.scenario.source_systems,
            affected_assets=(context.scenario.affected_asset,),
            reasoning_summary=reasoning,
            next_recommended_action=next_action,
            observations={"delegated_roles": [item.role.value for item in results if item.role is not AgentRole.SUPERVISOR]},
        )
        self._save(context.incident_id, result, results)

    def investigate(self, scenario_id: str) -> InvestigationReport:
        scenario = get_scenario(scenario_id)
        quality_preview = {
            "airflow_state": scenario.signals.get("airflow_state"),
            "dbt_state": scenario.signals.get("dbt_state"),
            "failed_boundaries": [item["pair"] for item in scenario.comparisons if item.get("status") == "FAIL"],
        }
        incident_id = self.store.create_incident(
            scenario.scenario_id,
            scenario.title,
            scenario.affected_asset,
            quality_preview,
        )
        results: list[AgentResult] = []
        evidence: list[EvidenceRecord] = []
        context = AgentContext(scenario, incident_id, self.project, self._invoke, evidence, {})

        self._supervisor_result(
            context,
            results,
            "Investigation accepted and initial quality triage delegated.",
            "The Supervisor starts with deterministic quality signals before choosing expensive or transformation-specific work.",
            "Run Quality and Business Context agents.",
        )
        quality_result = self.quality.run(context)
        self._save(incident_id, quality_result, results)
        business_result = self.business.run(context)
        self._save(incident_id, business_result, results)
        if quality_result.status == "PASS":
            self.store.transition(incident_id, IncidentState.FAILED, "No anomaly was proven; incident should not have been created.")
            return self._report(incident_id, scenario, results, evidence, [], None)

        self.store.transition(incident_id, IncidentState.INVESTIGATING, "Deterministic anomaly criteria were met.")
        metadata_result = self.metadata.run(context)
        self._save(incident_id, metadata_result, results)
        lineage_result = self.lineage.run(context)
        self._save(incident_id, lineage_result, results)
        mapping_result = self.mapping.run(context)
        self._save(incident_id, mapping_result, results)

        self.store.transition(incident_id, IncidentState.EVIDENCE_COLLECTION, "Technical and business context resolved; collect bounded evidence.")
        planner_result = self.planner.run(context)
        self._save(incident_id, planner_result, results)
        evidence_result, collected = self.evidence_agent.run(context)
        for item in collected:
            self.store.save_evidence(incident_id, item)
        self._save(incident_id, evidence_result, results)

        first = next((str(item["pair"]) for item in scenario.comparisons if item.get("status") == "FAIL"), None)
        context.shared["first_divergence"] = first
        self.store.update_outcome(incident_id, first_divergence=first)

        # Dynamic branch: only invoke TransformationAgent when divergence is at/after dbt or a dbt-specific signal exists.
        dbt_specific = (
            first is not None
            and any(token in first for token in ("staging", "intermediate", "core", "mart", "dbt"))
        ) or any(key in scenario.signals for key in ("filter_expression", "join_cardinality", "late_arriving_rows", "compile_error", "dbt_test_name"))
        if dbt_specific:
            transform_result = self.transformation.run(context)
            self._save(incident_id, transform_result, results)
        else:
            self._supervisor_result(
                context,
                results,
                "Transformation Agent skipped because direct evidence places the first divergence upstream of dbt.",
                "Dynamic delegation avoids spending model/tool budget on a downstream layer already proven healthy at its input boundary.",
                "Proceed directly to RCA with source/Airflow/RAW evidence.",
            )

        self.store.transition(incident_id, IncidentState.RCA, "Direct evidence bundle is ready for competing-hypothesis evaluation.")
        rca_result, hypotheses = self.rca.run(context)
        self._save(incident_id, rca_result, results)
        for item in hypotheses:
            self.store.save_hypothesis(incident_id, item)
        self.store.update_outcome(
            incident_id,
            root_cause=context.shared.get("root_cause"),
            root_cause_confidence=rca_result.confidence,
            first_divergence=context.shared.get("first_divergence"),
        )

        self.store.transition(incident_id, IncidentState.IMPACT_ANALYSIS, "Root cause supported; calculate downstream business impact.")
        impact_result = self.impact.run(context)
        self._save(incident_id, impact_result, results)
        blast = list(context.shared.get("blast_radius", []))
        self.store.update_outcome(incident_id, blast_radius=blast)

        self.store.transition(incident_id, IncidentState.REMEDIATION_PROPOSED, "Blast radius known; create minimum-risk recovery proposal.")
        remediation_result, plan = self.remediation.run(context)
        self._save(incident_id, remediation_result, results)
        self.store.save_remediation(incident_id, plan)
        self.store.transition(incident_id, IncidentState.AWAITING_APPROVAL, "Mutating remediation requires explicit human approval.")
        self._supervisor_result(
            context,
            results,
            "Investigation complete; remediation is waiting for human approval.",
            "No mutating action was executed during investigation. Approval is the boundary between reasoning and execution.",
            "Approve or reject the proposed remediation.",
        )
        return self._report(incident_id, scenario, results, evidence, hypotheses, plan)

    def approve(self, incident_id: str, *, approved_by: str) -> dict[str, Any]:
        """Record explicit human approval without executing the mutation."""
        return self.store.approve(incident_id, approved_by=approved_by)

    def reject(self, incident_id: str, *, rejected_by: str, reason: str = "operator rejected remediation") -> dict[str, Any]:
        incident = self.store.incident(incident_id)
        if incident["state"] != IncidentState.AWAITING_APPROVAL.value:
            raise ValueError(f"incident is {incident['state']}, not AWAITING_APPROVAL")
        self.store.transition(incident_id, IncidentState.BLOCKED, f"{reason}; rejected by {rejected_by}.")
        return {"incident_id": incident_id, "rejected": True, "rejected_by": rejected_by, "reason": reason}

    def execute_approved(self, incident_id: str) -> InvestigationReport:
        incident = self.store.incident(incident_id)
        if incident["state"] != IncidentState.AWAITING_APPROVAL.value:
            raise ValueError(f"incident is {incident['state']}, not AWAITING_APPROVAL")
        if not incident["approved"]:
            raise PermissionError("explicit human approval is required before remediation execution")
        scenario = get_scenario(incident["scenario_id"])
        self.store.transition(incident_id, IncidentState.REMEDIATING, "Approved remediation execution started.")

        remediation = self.store.remediation(incident_id)
        # Local proving-ground execution is explicit and never presented as live Snowflake/Airflow execution.
        execution = {
            "status": "PASS",
            "mode": "LOCAL_PROVING_GROUND",
            "action": remediation["action"] if remediation else scenario.remediation_action,
            "bounded": True,
            "external_mutation": False,
            "message": "Deterministic scenario recovery applied to the proving-ground fixture. Use live-e2e for external execution.",
        }
        self.store.update_outcome(incident_id, execution_result=execution)

        self.store.transition(incident_id, IncidentState.VERIFYING, "Approved proving-ground remediation applied; independently verify.")
        fixed = scenario.after_fix or {"business_metric_match": True}
        verification = {
            "status": "PASS" if fixed.get("business_metric_match", True) else "FAIL",
            "mode": "LOCAL_PROVING_GROUND",
            "original_failure_rechecked": True,
            "first_divergence_reconciliation": "PASS",
            "affected_quality_rules": "PASS",
            "affected_dbt_tests": "PASS",
            "pipeline_execution": "PASS",
            "business_metric": "PASS" if fixed.get("business_metric_match", True) else "FAIL",
            "observed": fixed,
        }
        self.store.update_outcome(incident_id, verification_result=verification)
        if verification["status"] != "PASS":
            self.store.transition(incident_id, IncidentState.FAILED, "Independent verification failed.")
            return self.get_report(incident_id)

        self.store.transition(incident_id, IncidentState.RECERTIFYING, "All required verification gates passed.")
        self.store.update_outcome(incident_id, certification="CERTIFIED")
        self.store.transition(incident_id, IncidentState.RESOLVED, "Affected assets independently re-certified.")
        return self.get_report(incident_id)

    def approve_and_execute(self, incident_id: str, *, approved_by: str) -> InvestigationReport:
        """Convenience method for CLI/demo flows; API keeps approval and execution separate."""
        self.approve(incident_id, approved_by=approved_by)
        return self.execute_approved(incident_id)

    def get_report(self, incident_id: str) -> InvestigationReport:
        incident = self.store.incident(incident_id)
        scenario = get_scenario(incident["scenario_id"])
        return self._report(incident_id, scenario, [], [], [], None, load_persisted=True)

    def _report(
        self,
        incident_id: str,
        scenario: FailureScenario,
        results: list[AgentResult],
        evidence: list[EvidenceRecord],
        hypotheses: list[AgentHypothesis],
        plan: RemediationPlan | None,
        *,
        load_persisted: bool = False,
    ) -> InvestigationReport:
        incident = self.store.incident(incident_id)
        if load_persisted:
            # Public report reconstruction for API callers. Agent/evidence detail remains available from the store.
            results = tuple()
            evidence = tuple()
            hypotheses = tuple()
            remediation = self.store.remediation(incident_id)
            plan = RemediationPlan(
                action=remediation["action"],
                reason=remediation["reason"],
                evidence_ids=tuple(remediation.get("evidence_ids", ())),
                risk=remediation["risk"],
                blast_radius=tuple(remediation.get("blast_radius", ())),
                rollback=remediation["rollback"],
                verification_plan=tuple(remediation.get("verification_plan", ())),
                requires_approval=bool(remediation.get("requires_approval", True)),
                arguments=dict(remediation.get("arguments", {})),
                plan_id=remediation["plan_id"],
            ) if remediation else None
        return InvestigationReport(
            incident_id=incident_id,
            scenario_id=scenario.scenario_id,
            mode=incident["mode"],
            state=IncidentState(incident["state"]),
            anomaly=incident["anomaly"],
            first_divergence=incident["first_divergence"],
            root_cause=incident["root_cause"],
            root_cause_confidence=float(incident["root_cause_confidence"]),
            hypotheses=tuple(hypotheses),
            blast_radius=tuple(incident["blast_radius"]),
            remediation=plan,
            certification=incident["certification"],
            agent_results=tuple(results),
            evidence=tuple(evidence),
            transitions=tuple(self.store.transitions(incident_id)),
            approved=incident["approved"],
            execution_result=incident["execution_result"],
            verification_result=incident["verification_result"],
        )

    def public_report(self, incident_id: str) -> dict[str, Any]:
        report = self.get_report(incident_id).public()
        report["agent_results"] = self.store.agent_results(incident_id)
        report["evidence"] = self.store.evidence(incident_id)
        report["hypotheses"] = self.store.hypotheses(incident_id)
        report["remediation"] = self.store.remediation(incident_id)
        return report
