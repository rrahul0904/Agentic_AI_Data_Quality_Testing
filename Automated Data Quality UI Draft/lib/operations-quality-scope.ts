type WorkspaceScopeIdentity = { projectId: string; environment: string };
type CurrentSourceScope = { sourceTableScopeId: string; selectedSourceTable: unknown };
type JsonRecord = Record<string, unknown>;

function normalized(value: unknown): string {
  return typeof value === "string" ? value.trim().normalize("NFKC").toLowerCase() : "";
}

/** Match the Rules API's immutable project/environment/source-table binding. */
export function matchesCurrentQualityPlan(value: unknown, scope: WorkspaceScopeIdentity, state: CurrentSourceScope): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value) || !state.sourceTableScopeId || !state.selectedSourceTable) return false;
  const plan = value as JsonRecord;
  return normalized(plan.project_id ?? plan.projectId) === normalized(scope.projectId)
    && normalized(plan.environment) === normalized(scope.environment)
    && normalized(plan.source_table_scope_id ?? plan.sourceTableScopeId) === normalized(state.sourceTableScopeId);
}

export function qualityRunsForTable(items: unknown[], sourceTableScopeId: string): JsonRecord[] {
  if (!sourceTableScopeId) return [];
  return items.filter((item): item is JsonRecord => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    .filter((item) => normalized(item.source_table_scope_id ?? item.sourceTableScopeId) === normalized(sourceTableScopeId));
}

export function qualityRunsForPlan(items: unknown[], planId: string): JsonRecord[] {
  if (!planId) return [];
  return items.filter((item): item is JsonRecord => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    .filter((item) => String(item.plan_id ?? item.planId ?? "") === planId);
}
