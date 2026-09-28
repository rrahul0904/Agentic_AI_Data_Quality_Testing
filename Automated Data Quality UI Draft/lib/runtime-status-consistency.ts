import type { ProjectAnalysisReport } from "./project-analysis";

type RecordValue = Record<string, unknown>;
export type RuntimeExecutionRecord = RecordValue & { run_id?: string; execution_status?: string; execution_verification_status?: string; verification_status?: string; data_quality_status?: string; plan?: RecordValue; current_step_details?: RecordValue; external_identifiers?: RecordValue[]; last_observation?: string };
export type RuntimeExecutionReference = { runId: string; assetName: string; kind: string; executionStatus: string; verificationStatus: string; dataQualityStatus: string; externalIdentifier?: string; lastObserved?: string; scopeMatch: "MATCHED" | "NOT_RECORDED" };

const record = (value: unknown): RecordValue | null => value && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : null;
const norm = (value: unknown) => typeof value === "string" ? value.trim().toLocaleLowerCase("en-US") : "";
const rows = (value: unknown) => Array.isArray(value) ? value.map(record).filter((item): item is RecordValue => Boolean(item)) : [];

/** Exact-name navigation only; this never marks lineage edges observed. */
export function correlateRuntimeExecutions(report: ProjectAnalysisReport | null | undefined, executions: RuntimeExecutionRecord[]): RuntimeExecutionReference[] {
  if (!report?.project_id || !report.environment) return [];
  const byName = new Map<string, number>();
  for (const node of report.graph?.nodes ?? []) byName.set(norm(node.name), (byName.get(norm(node.name)) ?? 0) + 1);
  const result: RuntimeExecutionReference[] = [];
  for (const execution of executions) {
    const plan = record(execution.plan) ?? {};
    if (norm(plan.project_id) !== norm(report.project_id) || norm(plan.environment) !== norm(report.environment)) continue;
    const planScope = typeof plan.source_table_scope_id === "string" ? plan.source_table_scope_id : "";
    const analysisScope = typeof report.source_table_scope_id === "string" ? report.source_table_scope_id : "";
    if (planScope && analysisScope && planScope !== analysisScope) continue;
    const runId = typeof execution.run_id === "string" ? execution.run_id : "";
    const step = record(execution.current_step_details) ?? {};
    const assetName = typeof step.asset === "string" ? step.asset.trim() : "";
    if (!runId || !assetName || byName.get(norm(assetName)) !== 1) continue;
    const sequence = Number(step.sequence);
    const external = rows(execution.external_identifiers).find((item) => Number(item.step_sequence) === sequence && item.value);
    result.push({ runId, assetName, kind: typeof step.kind === "string" ? step.kind : "", executionStatus: execution.execution_status || "NOT_CHECKED", verificationStatus: execution.execution_verification_status || execution.verification_status || "NOT_CHECKED", dataQualityStatus: execution.data_quality_status || "NOT_CHECKED", externalIdentifier: external ? String(external.value) : undefined, lastObserved: execution.last_observation, scopeMatch: planScope && analysisScope && planScope === analysisScope ? "MATCHED" : "NOT_RECORDED" });
  }
  return result.sort((a, b) => (Date.parse(b.lastObserved || "") || 0) - (Date.parse(a.lastObserved || "") || 0));
}

export function lineageRuntimeRefresh(report: ProjectAnalysisReport | null | undefined) {
  const runtime = report?.runtime;
  return { status: runtime?.status || "NOT_RUN", refreshedAt: runtime?.refreshed_at || null, note: runtime?.note || "No runtime refresh is recorded for this lineage snapshot.", analysisCreatedAt: report?.created_at || null, observedEdges: runtime?.observed_edge_count ?? 0, observedNodes: runtime?.observed_node_count ?? 0 };
}
