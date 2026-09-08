# Agent runtime

The repository contains two complementary agent surfaces.

## Investigation control plane

The primary data-quality incident workflow is a 12-role evidence-grounded control plane:

1. Supervisor
2. Metadata
3. Business Context
4. Lineage
5. Transformation
6. Mapping
7. Quality/Test
8. Execution Planning
9. Evidence
10. RCA
11. Impact
12. Remediation

The Supervisor delegates dynamically from measured evidence. A source→RAW divergence can bypass Transformation analysis; a dbt-layer divergence invokes it. Specialist investigation agents have explicit read-only tool policies. Mutating recovery is not allowed during investigation.

Lifecycle: DETECTED → INVESTIGATING → EVIDENCE_COLLECTION → RCA → IMPACT_ANALYSIS → REMEDIATION_PROPOSED → AWAITING_APPROVAL → REMEDIATING → VERIFYING → RECERTIFYING → RESOLVED. BLOCKED and FAILED are terminal alternatives.

Evidence uses provenance tiers T1 direct measurement, T2 runtime metadata, T3 static analysis, T4 historical inference, and T5 LLM interpretation. RCA consumes the persisted evidence bundle; benchmark expected answers are structurally excluded from agent runtime inputs.

## Generic provider/tool runtime

`AgentRuntime` remains the provider-neutral LLM → governed tool → evidence loop used by sessions and live-provider verification. It preserves assistant tool-call turns in provider-valid form for OpenAI-compatible, Azure, Anthropic, and Gemini transports.

`PlannerAgent` and `RepairAgent` remain bounded engineering helpers. They are not substitutes for the 12-role incident control plane.

## Safety

Agents reason and propose. Deterministic tools measure and execute. Direct evidence outranks LLM interpretation.

Read-only investigation tools are allowlisted. Remediation proposals include risk, rollback, evidence IDs, bounded Airflow/dbt recovery, and a verification plan. Approval and execution are separate API operations.

## Local and live execution

Local incident execution is explicitly labeled `LOCAL_PROVING_GROUND`. It proves orchestration, evidence, hypotheses, first-divergence localization, impact, approval, recovery planning, verification, and certification without pretending to mutate Snowflake or Airflow.

Live Snowflake, dbt/Snowflake, Airflow failure/recovery, and LLM tool-round-trip acceptance are separate fail-closed workflows documented in `docs/LIVE_E2E.md`.
