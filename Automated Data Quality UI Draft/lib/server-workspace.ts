import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

export type WorkspaceScope = {
  projectId: string;
  environment: string;
  name: string;
  source: "deployment" | "persisted_project" | "default";
  scopeLocked?: boolean;
  requestedProjectId?: string;
  requestedEnvironment?: string;
};

export type CurrentWorkspaceState = {
  sourceTableScopeId: string;
  analysisScopeId: string;
  qualityPlanScopeId: string;
  selectedSourceTable: Record<string, unknown> | null;
  selectedAssetIdentity: CanonicalAssetIdentity | null;
  sourceName: string;
  targetName: string;
};

export type CanonicalAssetIdentity = {
  identityVersion: 1;
  assetId?: string;
  connection?: string;
  database?: string;
  schema?: string;
  table?: string;
};

const STATE_FILE = process.env.ADE_UI_WORKSPACE_STATE_FILE
  ?? path.join(process.cwd(), ".ade-ui", "onboarding-state.json");

function clean(value: unknown, maximum = 200): string {
  return typeof value === "string" ? value.trim().slice(0, maximum) : "";
}

export function projectSlug(name: string): string {
  return name
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

function cookie(request: Request | undefined, name: string): string {
  const header = request?.headers.get("cookie") ?? "";
  for (const item of header.split(";")) {
    const [key, ...parts] = item.trim().split("=");
    if (key === name) return decodeURIComponent(parts.join("="));
  }
  return "";
}

async function persistedProject(): Promise<Record<string, unknown>> {
  try {
    const state = JSON.parse(await readFile(STATE_FILE, "utf8")) as Record<string, unknown>;
    return state.projectDefinition && typeof state.projectDefinition === "object"
      ? state.projectDefinition as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

async function projectRegistry(): Promise<Array<Record<string, unknown>>> {
  try {
    const registryPath = path.join(process.cwd(), ".ade-ui", "projects.json");
    const parsed = JSON.parse(await readFile(registryPath, "utf8"));
    return Array.isArray(parsed) ? parsed.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : [];
  } catch {
    return [];
  }
}

async function currentWorkflow(scope: WorkspaceScope): Promise<Record<string, unknown> | null> {
  const workflowPath = path.join(process.cwd(), ".ade-ui", "projects", projectSlug(scope.projectId) || "data-quality-project", "workflow.json");
  try { return JSON.parse(await readFile(workflowPath, "utf8")) as Record<string, unknown>; }
  catch { return null; }
}

export async function currentWorkspaceState(scope: WorkspaceScope): Promise<CurrentWorkspaceState> {
  const workflow = await currentWorkflow(scope);
  const selected = workflow?.selectedSourceTable && typeof workflow.selectedSourceTable === "object"
    ? workflow.selectedSourceTable as Record<string, unknown>
    : null;
  const sourceTableScopeId = typeof workflow?.sourceTableScopeId === "string" ? workflow.sourceTableScopeId : "";
  const sourceSchema = clean(selected?.schema, 100);
  const sourceTable = clean(selected?.table, 200);
  const targetSchema = "RAW";
  const sourceName = sourceSchema && sourceTable ? `postgres.${sourceSchema}.${sourceTable}`.toLowerCase() : "";
  const targetName = sourceTable ? `raw.${sourceTable}`.toLowerCase() : "";
  const selectedAssetIdentity = sourceTableScopeId ? canonicalAssetIdentity(selected) : null;
  return {
    sourceTableScopeId,
    analysisScopeId: typeof workflow?.analysisScopeId === "string" ? workflow.analysisScopeId : "",
    qualityPlanScopeId: typeof workflow?.qualityPlanScopeId === "string" ? workflow.qualityPlanScopeId : "",
    selectedSourceTable: selected,
    selectedAssetIdentity,
    sourceName,
    targetName,
  };
}

function normalizeIdentityPart(value: unknown, maximum = 200): string {
  return clean(value, maximum).normalize("NFKC").toLowerCase();
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    const normalized = normalizeIdentityPart(value);
    if (normalized) return normalized;
  }
  return "";
}

function identityFromRecord(value: Record<string, unknown>): CanonicalAssetIdentity | null {
  const properties = record(value.properties);
  const canonical = record(value.canonical_asset_identity) ?? record(value.canonicalAssetIdentity);
  const sources = [canonical, value, properties].filter((item): item is Record<string, unknown> => Boolean(item));
  const read = (...names: string[]): string => firstString(...sources.flatMap((source) => names.map((name) => source[name])));
  const assetId = read("asset_id", "assetId", "source_table_id", "sourceTableId", "discovery_asset_id", "discoveryAssetId");
  const connection = read("connection_id", "connectionId", "connector", "connector_id", "connectorId", "connection");
  const database = read("database", "database_name", "databaseName");
  const schema = read("schema", "schema_name", "schemaName");
  const table = read("table", "table_name", "tableName", "relation", "relation_name", "relationName");
  if (!assetId && !table) {
    const qualified = firstString(value.qualified_name, value.qualifiedName, value.asset_name, value.assetName, value.source_table, value.sourceTable, value.asset);
    const parts = qualified.split(".").map((part) => normalizeIdentityPart(part)).filter(Boolean);
    if (parts.length === 3) return { identityVersion: 1, connection: parts[0], schema: parts[1], table: parts[2] };
    if (parts.length === 4) return { identityVersion: 1, connection: parts[0], database: parts[1], schema: parts[2], table: parts[3] };
    return null;
  }
  return { identityVersion: 1, ...(assetId ? { assetId } : {}), ...(connection ? { connection } : {}), ...(database ? { database } : {}), ...(schema ? { schema } : {}), ...(table ? { table } : {}) };
}

export function canonicalAssetIdentity(value: unknown): CanonicalAssetIdentity | null {
  const item = record(value);
  if (!item) return null;
  return identityFromRecord(item);
}

function identityCandidates(value: unknown): CanonicalAssetIdentity[] {
  const item = record(value);
  if (!item) return [];
  const nestedRecords = [item.plan, item.asset, item.source, item.target, item.node, item.parameters, item.properties]
    .map(record)
    .filter((candidate): candidate is Record<string, unknown> => Boolean(candidate));
  const nestedArrayRecords = [item.steps, item.assets, item.nodes]
    .flatMap((entries) => Array.isArray(entries) ? entries : [])
    .map(record)
    .filter((candidate): candidate is Record<string, unknown> => Boolean(candidate));
  const candidates = [item, ...nestedRecords, ...nestedArrayRecords]
    .filter((candidate): candidate is Record<string, unknown> => Boolean(candidate))
    .map(identityFromRecord)
    .filter((candidate): candidate is CanonicalAssetIdentity => Boolean(candidate));
  const unique = new Map(candidates.map((candidate) => [JSON.stringify(candidate), candidate]));
  return [...unique.values()];
}

function tupleMatches(left: CanonicalAssetIdentity, right: CanonicalAssetIdentity): boolean {
  if (!left.table || !right.table || left.table !== right.table) return false;
  for (const key of ["connection", "database", "schema"] as const) {
    if (left[key] && right[key] && left[key] !== right[key]) return false;
    if (left[key] !== right[key]) return false;
  }
  return true;
}

export function recordMatchesCurrentTable(value: unknown, state: CurrentWorkspaceState): boolean {
  const selected = state.selectedAssetIdentity;
  if (!selected || !value) return false;
  return identityCandidates(value).some((candidate) => {
    if (selected.assetId && candidate.assetId) return selected.assetId === candidate.assetId;
    return tupleMatches(selected, candidate);
  });
}

export async function currentWorkspaceRunIds(scope: WorkspaceScope): Promise<Set<string>> {
  const state = await currentWorkspaceState(scope);
  if (!state.sourceTableScopeId || state.analysisScopeId !== state.sourceTableScopeId || state.qualityPlanScopeId !== state.sourceTableScopeId) return new Set();
  const apiBase = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";
  try {
    const latestResponse = await fetch(`${apiBase}/api/v1/quality-plans/latest?${workspaceQuery(scope)}`, { cache: "no-store", signal: AbortSignal.timeout(30000) });
    if (!latestResponse.ok) return new Set();
    const latest = await latestResponse.json() as Record<string, unknown>;
    const planId = typeof latest.plan_id === "string" ? latest.plan_id : "";
    if (!planId) return new Set();
    const runsResponse = await fetch(`${apiBase}/api/v1/quality-plans/${encodeURIComponent(planId)}/runs`, { cache: "no-store", signal: AbortSignal.timeout(30000) });
    if (!runsResponse.ok) return new Set();
    const runs = await runsResponse.json() as Record<string, unknown>;
    const items = Array.isArray(runs.items) ? runs.items : [];
    return new Set(items.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const runId = (item as Record<string, unknown>).run_id ?? (item as Record<string, unknown>).runId;
      return typeof runId === "string" && runId ? [runId] : [];
    }));
  } catch {
    return new Set();
  }
}

export function recordMatchesCurrentExecution(value: unknown, state: CurrentWorkspaceState, runIds: Set<string>): boolean {
  if (!value || !runIds.size || !recordMatchesCurrentTable(value, state)) return false;
  const item = value as Record<string, unknown>;
  const runId = item.run_id ?? item.runId ?? (item.result && typeof item.result === "object" ? (item.result as Record<string, unknown>).run_id : undefined);
  return typeof runId === "string" && runIds.has(runId);
}

function currentSourceScope(workflow: Record<string, unknown> | null): string {
  const selected = workflow?.selectedSourceTable && typeof workflow.selectedSourceTable === "object" ? workflow.selectedSourceTable as Record<string, unknown> : null;
  const scopeId = typeof workflow?.sourceTableScopeId === "string" ? workflow.sourceTableScopeId : "";
  return selected && scopeId === selected.id ? scopeId : "";
}

export async function resolveWorkspace(request?: Request): Promise<WorkspaceScope> {
  const registry = await projectRegistry();
  const explicitProject = clean(request ? new URL(request.url).searchParams.get("project_id") : "")
    || clean(cookie(request, "ade-project-id"));
  // Older tabs can omit the query string. When there is exactly one saved
  // project, use it as the deterministic workspace instead of falling back
  // to the empty legacy project and hiding its connection metadata.
  const requestedProject = explicitProject || (registry.length === 1 ? clean(registry[0]?.id) : "");
  const requestedRecord = registry.find((item) => clean(item.id) === requestedProject);
  const persisted = requestedRecord?.projectDefinition && typeof requestedRecord.projectDefinition === "object"
    ? requestedRecord.projectDefinition as Record<string, unknown>
    : await persistedProject();
  const hasPersistedProject = Object.keys(persisted).length > 0;
  const persistedName = clean(persisted.name) || "Data Quality Project";
  const deploymentProject = clean(process.env.ADE_UI_PROJECT_ID);
  const deploymentEnvironment = clean(process.env.ADE_UI_ENVIRONMENT, 100);
  const requestedEnvironment = clean(request ? new URL(request.url).searchParams.get("environment") : "", 100)
    || clean(cookie(request, "ade-environment"), 100);
  const derivedProject = projectSlug(persistedName);
  const projectId = deploymentProject || requestedProject || (hasPersistedProject ? derivedProject : "data-quality-project");
  const environment = (deploymentEnvironment || requestedEnvironment || clean(persisted.environment, 100) || "development").toLowerCase();
  return {
    projectId,
    environment,
    name: persistedName,
    source: deploymentProject ? "deployment" : hasPersistedProject ? "persisted_project" : "default",
    scopeLocked: Boolean(deploymentProject || deploymentEnvironment),
    requestedProjectId: explicitProject || undefined,
    requestedEnvironment: requestedEnvironment || undefined,
  };
}

export function workspaceQuery(scope: WorkspaceScope): string {
  return `project_id=${encodeURIComponent(scope.projectId)}&environment=${encodeURIComponent(scope.environment)}`;
}

/**
 * The UI keeps onboarding evidence per project.  Backend records are retained
 * for audit/history, but a freshly reset project must not render those old
 * records as if they belonged to its current workflow.
 */
export async function hasCurrentWorkspaceEvidence(scope: WorkspaceScope): Promise<boolean> {
  const value = await currentWorkflow(scope);
  if (!currentSourceScope(value)) return false;
  const discoveries = value?.discoveries && typeof value.discoveries === "object" ? Object.values(value.discoveries as Record<string, Record<string, unknown>>) : [];
  return discoveries.some((item) => item?.status === "PASS");
}

export async function hasCurrentWorkspaceAnalysis(scope: WorkspaceScope): Promise<boolean> {
  const value = await currentWorkflow(scope);
  const sourceScope = currentSourceScope(value);
  return Boolean(sourceScope && value?.analysisScopeId === sourceScope && await hasCurrentWorkspaceEvidence(scope));
}

export async function hasCurrentWorkspacePlan(scope: WorkspaceScope): Promise<boolean> {
  const value = await currentWorkflow(scope);
  const sourceScope = currentSourceScope(value);
  return Boolean(sourceScope && value?.qualityPlanScopeId === sourceScope && await hasCurrentWorkspaceAnalysis(scope));
}

export async function markCurrentWorkspaceStage(scope: WorkspaceScope, stage: "analysisScopeId" | "qualityPlanScopeId"): Promise<void> {
  const workflow = await currentWorkflow(scope);
  const sourceScope = currentSourceScope(workflow);
  if (!workflow || !sourceScope) return;
  workflow[stage] = sourceScope;
  // A new analysis invalidates the previous quality-plan revision. The old
  // plan remains in the backend history, but it must not appear executable for
  // a newly scoped source-table graph.
  if (stage === "analysisScopeId") workflow.qualityPlanScopeId = undefined;
  const workflowPath = path.join(process.cwd(), ".ade-ui", "projects", projectSlug(scope.projectId) || "data-quality-project", "workflow.json");
  await mkdir(path.dirname(workflowPath), { recursive: true });
  await writeFile(workflowPath, `${JSON.stringify(workflow, null, 2)}\n`, { mode: 0o600 });
}

export function workspaceCookieHeaders(scope: WorkspaceScope): Headers {
  const headers = new Headers({ "Cache-Control": "no-store" });
  const common = "Path=/; SameSite=Strict; HttpOnly";
  headers.append("Set-Cookie", `ade-project-id=${encodeURIComponent(scope.projectId)}; ${common}`);
  headers.append("Set-Cookie", `ade-environment=${encodeURIComponent(scope.environment)}; ${common}`);
  return headers;
}
