# Phase 6 presentation stories

These stories are intentionally short and use the same language as the product. They are presentation paths, not instructions to run live pipelines. Confirm the selected project, environment, and execution mode before any approved live action.

## 1. Onboard one table and create a governed plan

**Story:** Start with a PostgreSQL source table and show how the control plane turns metadata into a reviewable quality plan.

**Path:** Project management → Data onboarding → select one source table → review discovered source, ingestion, transformation, and target objects → Object & flows → Map flows → Quality rules.

**Show:** table scope, discovered dependencies, planned lineage, grouped quality checks, and editable rule details. Explain that discovery and proposed lineage are evidence-backed planning artifacts; they are not proof that a pipeline has run.

## 2. Run one approved job and follow it in Monitoring

**Story:** Demonstrate explicit execution scope and a traceable lifecycle for one job or selected sequence.

**Path:** Actions → choose Single job, Selected sequence, or End-to-end → review the exact plan and approval contract → submit → Monitoring → open the selected job.

**Show:** project and environment, selected asset, dependencies, submission/execution/data-quality states, current step, observation time, external run identifiers, attempts, uncertainty, and exact evidence links. Do not describe `Submitted` or `Completed` as data-quality success until verification is recorded.

## 3. Explain a failed run without exposing raw JSON

**Story:** Show how a failed execution becomes an incident and then an evidence-bounded investigation.

**Path:** Monitoring → select the failed job → open exact evidence → Incidents → select the incident → Investigations.

**Show:** what failed, affected boundary, failed checks, direct evidence, competing hypotheses, confidence, and the next approved action. Keep confirmed facts separate from possible causes; if evidence is missing, say so explicitly.

## 4. Verify a source-to-target result

**Story:** Demonstrate read-only data-quality verification after a pipeline run.

**Path:** Reconciliation → choose source database/table and target database/table → choose row count, key difference, null, or duplicate check → run the read-only comparison → open verification history.

**Show:** source and target identity, check type, result, limits, pipeline/run correlation, and drill-down evidence. A baseline comparison does not create an incident and does not execute Airflow, dbt, COPY, or Snowpipe.

## 5. Ask for an AI advisory review

**Story:** Let a reviewer request bounded AI analysis of deterministic lineage or a run without allowing AI to authorize execution.

**Path:** Map flows or Monitoring → select the table/run scope → Run AI verification → review confidence, supporting evidence, conflicts, uncertainty, provider/model, and approval requirement.

**Show:** the states Not invoked, Ready, Running, Completed, Needs human approval, or Unavailable — configure AI. AI may explain or challenge a mapping; it cannot silently approve a link, expand execution scope, or authorize a job.

## Presentation checklist

- State whether the screen is showing configuration, a dry run, live execution, verification, or certification.
- Keep the project and environment visible in the story.
- Use Monitoring for lifecycle status and evidence, Map flows for planned/observed lineage, Incidents for operational records, and Investigations for RCA.
- Prefer the user-facing summary and open technical details only when asked.
- If a connector is unavailable or no live run exists, present that as a truthful state rather than a successful result.
