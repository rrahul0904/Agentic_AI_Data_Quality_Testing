import { chmod, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import type { ConnectionProfile, ConnectionTestResult, DiscoveredAsset, DiscoveryCategory, DiscoveryResult, OnboardingBootstrap, PipelineLayer, SelectedSourceTable } from "../../../lib/onboarding";
import { validateConnectionProfile, validateDiscoveryEvidence } from "../../../lib/onboarding";
import { nextWorkflowGeneration, projectSlug, resolveWorkspace, workspaceCookieHeaders, workspaceRevision, type WorkspaceScope } from "../../../lib/server-workspace";
import { isPhase4Fixture, phase4OnboardingWorkspace } from "../../../lib/server-test-fixture";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";
const CANONICAL_ROOT = process.env.ADE_CANONICAL_PROJECT_ROOT ?? "/Users/297159/Documents/Agentic_AI/Automated Data Quality Testing";
const UI_ROOT = "/Users/297159/Documents/Agentic_AI/Automated Data Quality UI Draft";
const STATE_DIR = path.join(UI_ROOT, ".ade-ui");
const STATE_FILE = path.join(STATE_DIR, "onboarding-connections.json");
const WORKFLOW_STATE_FILE = path.join(STATE_DIR, "onboarding-state.json");
const PROJECTS_FILE = path.join(STATE_DIR, "projects.json");
const PROJECTS_DIR = path.join(STATE_DIR, "projects");
const DEFAULT_PROJECT_NAME = "Data Quality Testing - Beta";
const CONNECTION_DB = path.join(STATE_DIR, "connections.db");
const METADATA_DB = path.join(STATE_DIR, "metadata.db");
const ALLOWED_LOCAL_ROOT = "/Users/297159/Documents/Agentic_AI";
const RUNTIME_ROOT = process.env.ADE_RUNTIME_ROOT ?? path.join(CANONICAL_ROOT, "runtime/hospitality-data-reliability-lab");
const execFileAsync = promisify(execFile);

function errorText(input: unknown): string {
  if (typeof input === "string") return input;
  if (input && typeof input === "object") {
    const item = input as Record<string, unknown>;
    return value(item.message) || value(item.error) || value(item.reason);
  }
  return "";
}

async function backend(endpoint: string, init?: RequestInit, timeoutMs = 15000): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${endpoint}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  const body = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(errorText(body.detail) || errorText(body.error) || `ADE API returned ${response.status}`);
  return body;
}

async function runtimeProfile(): Promise<Record<string, unknown>> {
  try { return await backend("/api/v1/runtime-profile"); }
  catch { return { profile: {} }; }
}

/** Read only non-secret runtime hints for population. Values of credential-like
 * variables are never returned to the UI; their names are enough to select the
 * environment reference used by the adapters. */
async function runtimeHints(): Promise<Record<string, string>> {
  try {
    const content = await readFile(path.join(RUNTIME_ROOT, ".env"), "utf8");
    const allowed = new Set([
      "SOURCE_POSTGRES_HOST", "SOURCE_POSTGRES_PORT", "SOURCE_POSTGRES_DB", "SOURCE_POSTGRES_USER",
      "SOURCE_POSTGRES_DSN", "SOURCE_POSTGRES_CONN", "ADE_POSTGRES_DSN",
      "ADE_SNOWFLAKE_ACCOUNT", "SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER", "SNOWFLAKE_USER",
      "ADE_SNOWFLAKE_DATABASE", "SNOWFLAKE_DATABASE", "ADE_SNOWFLAKE_SCHEMA", "SNOWFLAKE_SCHEMA",
      "ADE_SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_WAREHOUSE", "ADE_SNOWFLAKE_ROLE", "SNOWFLAKE_ROLE",
      "ADE_AIRFLOW_BASE_URL", "ADE_AIRFLOW_URL", "ADE_AIRFLOW_VERSION", "AIRFLOW_ADMIN_USERNAME",
      "AIRFLOW_ADMIN_PASSWORD", "ADE_AIRFLOW_PASSWORD", "ADE_AIRFLOW_TOKEN", "ADE_SNOWFLAKE_PASSWORD",
    ]);
    const result: Record<string, string> = {};
    for (const line of content.split(/\r?\n/)) {
      const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (!match || !allowed.has(match[1])) continue;
      const key = match[1];
      // Never copy secret values into process responses or persisted profiles.
      if (/password|token|dsn|conn/i.test(key)) {
        if (match[2]) result[`${key}__present`] = "true";
        continue;
      }
      result[key] = match[2].replace(/^['"]|['"]$/g, "");
    }
    return result;
  } catch { return {}; }
}

async function currentConnectionChecks(scope: WorkspaceScope): Promise<Record<string, ConnectionTestResult>> {
  const query = new URLSearchParams({ project_id: scope.projectId, environment: scope.environment }).toString();
  const adapters: Record<string, string> = {
    postgres: `/api/v1/connections/postgres/metadata?${query}`,
    snowflake: `/api/v1/connections/snowflake/metadata?${query}`,
    airflow: `/api/v1/connections/airflow/metadata?${query}`,
    dbt: `/api/v1/connections/dbt/status?${query}`,
  };
  const checkedAt = new Date().toISOString();
  const entries = await Promise.all(Object.entries(adapters).map(async ([kind, endpoint]) => {
    try {
      const result = await backend(endpoint, undefined, 2500);
      const status = value(result.status).toUpperCase();
      const passed = ["PASS", "READY", "HEALTHY", "CONNECTED", "EXECUTION_EVIDENCE_FOUND"].includes(status);
      return [kind, {
        status: passed ? "PASS" : "UNVERIFIED",
        detail: passed ? (kind === "dbt" && value(result.execution_status) === "NOT_RUN_OR_NO_RUN_RESULTS" ? "dbt project is ready; no execution evidence is recorded" : "Current adapter read passed") : errorText(result.reason) || errorText(result.detail) || "Current adapter did not return a passing state",
        source: "Current adapter read",
        testedAt: checkedAt,
        metadata: result,
      } satisfies ConnectionTestResult] as const;
    } catch (error) {
      return [kind, {
        status: "UNVERIFIED",
        detail: error instanceof Error ? error.message : "Current adapter read unavailable",
        source: "Current adapter read",
        testedAt: checkedAt,
      } satisfies ConnectionTestResult] as const;
    }
  }));
  return Object.fromEntries(entries);
}

function value(value: unknown): string { return typeof value === "string" ? value : ""; }

function labelFrom(valueToLabel: unknown, fallback: string): string {
  const label = value(valueToLabel).trim();
  return label ? `${label} · ${fallback}` : fallback;
}

function airflowLabel(baseUrl: unknown): string {
  try { return labelFrom(new URL(value(baseUrl)).hostname, "Apache Airflow"); }
  catch { return "Apache Airflow"; }
}

async function dbtProjectLabel(projectDir: string): Promise<string> {
  try {
    const content = await readFile(path.join(projectDir, "dbt_project.yml"), "utf8");
    const match = content.match(/^name:\s*['"]?([^'"#\r\n]+)['"]?/m);
    return labelFrom(match?.[1]?.trim(), "dbt project");
  } catch { return labelFrom(path.basename(projectDir), "dbt project"); }
}

async function detectedFileRoot(profile: Record<string, unknown>, projectRoot: string): Promise<string> {
  const candidates = [profile.source_data_dir, profile.data_dir, profile.landing_dir, profile.files_root, path.join(projectRoot, "data"), path.join(CANONICAL_ROOT, "data")];
  for (const candidate of candidates) {
    const candidatePath = value(candidate);
    if (!candidatePath) continue;
    try {
      if ((await stat(candidatePath)).isDirectory()) {
        const children = await readdir(candidatePath, { withFileTypes: true });
        const directories = children.filter((entry) => entry.isDirectory());
        const files = children.filter((entry) => entry.isFile());
        if (!files.length && directories.length === 1) return path.join(candidatePath, directories[0].name);
        return candidatePath;
      }
    } catch { /* candidate is absent */ }
  }
  return "";
}

function safePath(input: unknown): string {
  const resolved = path.resolve(value(input));
  if (resolved !== ALLOWED_LOCAL_ROOT && !resolved.startsWith(`${ALLOWED_LOCAL_ROOT}${path.sep}`)) throw new Error("Local paths must stay inside the Agentic_AI workspace");
  return resolved;
}

async function readSaved(): Promise<ConnectionProfile[]> {
  try {
    const parsed = JSON.parse(await readFile(STATE_FILE, "utf8"));
    return Array.isArray(parsed) ? parsed.map(validateConnectionProfile) : [];
  } catch { return []; }
}

async function writeSaved(profiles: ConnectionProfile[]): Promise<void> {
  await mkdir(STATE_DIR, { recursive: true });
  await writeFile(STATE_FILE, `${JSON.stringify(profiles.map(validateConnectionProfile), null, 2)}\n`, { mode: 0o600 });
}

function profileFingerprint(profile: ConnectionProfile): string {
  return JSON.stringify({ name: profile.name, kind: profile.kind, environment: profile.environment, source: profile.source, enabled: profile.enabled, config: profile.config });
}

type WorkflowState = {
  /** Incremented whenever the active source-table scope changes or is cleared. */
  workspaceGeneration?: number;
  tests: Record<string, ConnectionTestResult>;
  discoveries: Record<string, DiscoveryResult>;
  selectedAssets: string[];
  selectedSourceTable?: SelectedSourceTable;
  selectedSourceTables?: SelectedSourceTable[];
  discoveriesByTable?: Record<string, Record<string, DiscoveryResult>>;
  sourceTableScopeId?: string;
  analysisScopeId?: string;
  qualityPlanScopeId?: string;
  projectDefinition?: Record<string, string>;
  projectSavedAt?: string;
};

type ProjectRecord = {
  id: string;
  projectDefinition: Record<string, string>;
  projectSavedAt?: string;
  createdAt: string;
};

function emptyWorkflowState(): WorkflowState {
  return { workspaceGeneration: 0, tests: {}, discoveries: {}, discoveriesByTable: {}, selectedAssets: [] };
}

function workflowGeneration(state: WorkflowState): number {
  return typeof state.workspaceGeneration === "number" && Number.isSafeInteger(state.workspaceGeneration) && state.workspaceGeneration >= 0
    ? state.workspaceGeneration
    : 0;
}

function advanceWorkflowGeneration(state: WorkflowState): void {
  state.workspaceGeneration = nextWorkflowGeneration(workflowGeneration(state));
}

function onboardingHeaders(scope: WorkspaceScope, state?: WorkflowState | number): Headers {
  const headers = workspaceCookieHeaders(scope);
  const generation = typeof state === "number" ? state : workflowGeneration(state ?? emptyWorkflowState());
  const revision = workspaceRevision(scope, generation);
  headers.set("X-ADQ-Workspace-Revision", revision);
  // This is an opaque cache key, not an authentication value. It must remain
  // readable so browser-side scoped URLs can separate a cleared scope from a
  // prior session response even when a page owns its own fetch state.
  headers.append("Set-Cookie", `ade-workspace-revision=${encodeURIComponent(revision)}; Path=/; SameSite=Strict`);
  return headers;
}

function sourceTablesFromState(value: Partial<WorkflowState>): SelectedSourceTable[] {
  const many = Array.isArray(value.selectedSourceTables) ? value.selectedSourceTables.filter((item): item is SelectedSourceTable => !!item && typeof item === "object" && typeof item.id === "string") : [];
  if (many.length) return many;
  return value.selectedSourceTable ? [value.selectedSourceTable] : [];
}

async function readProjects(): Promise<ProjectRecord[]> {
  try {
    const parsed = JSON.parse(await readFile(PROJECTS_FILE, "utf8"));
    return Array.isArray(parsed) ? parsed.filter((item): item is ProjectRecord => !!item && typeof item === "object" && typeof item.id === "string" && typeof item.projectDefinition === "object") : [];
  } catch { return []; }
}

async function writeProjects(projects: ProjectRecord[]): Promise<void> {
  await mkdir(STATE_DIR, { recursive: true });
  await writeFile(PROJECTS_FILE, `${JSON.stringify(projects, null, 2)}\n`, { mode: 0o600 });
}

function projectFile(projectIdValue: string, fileName: string): string {
  const safeId = projectSlug(projectIdValue) || "data-quality-project";
  return path.join(PROJECTS_DIR, safeId, fileName);
}

async function readProjectConnections(projectIdValue: string): Promise<ConnectionProfile[]> {
  try { return JSON.parse(await readFile(projectFile(projectIdValue, "connections.json"), "utf8")) as ConnectionProfile[]; }
  catch { return projectSlug(projectIdValue) === projectSlug(DEFAULT_PROJECT_NAME) ? readSaved() : []; }
}

async function writeProjectConnections(projectIdValue: string, profiles: ConnectionProfile[]): Promise<void> {
  const directory = path.dirname(projectFile(projectIdValue, "connections.json"));
  await mkdir(directory, { recursive: true });
  await writeFile(projectFile(projectIdValue, "connections.json"), `${JSON.stringify(profiles.map(validateConnectionProfile), null, 2)}\n`, { mode: 0o600 });
}

async function readProjectWorkflow(projectIdValue: string): Promise<WorkflowState> {
  try {
    const value = JSON.parse(await readFile(projectFile(projectIdValue, "workflow.json"), "utf8")) as Partial<WorkflowState>;
    return { workspaceGeneration: typeof value.workspaceGeneration === "number" ? value.workspaceGeneration : 0, tests: value.tests && typeof value.tests === "object" ? value.tests : {}, discoveries: value.discoveries && typeof value.discoveries === "object" ? value.discoveries : {}, discoveriesByTable: value.discoveriesByTable && typeof value.discoveriesByTable === "object" ? value.discoveriesByTable as Record<string, Record<string, DiscoveryResult>> : {}, selectedAssets: Array.isArray(value.selectedAssets) ? value.selectedAssets.filter((item): item is string => typeof item === "string") : [], selectedSourceTable: value.selectedSourceTable && typeof value.selectedSourceTable === "object" ? value.selectedSourceTable as SelectedSourceTable : undefined, selectedSourceTables: sourceTablesFromState(value), sourceTableScopeId: typeof value.sourceTableScopeId === "string" ? value.sourceTableScopeId : undefined, analysisScopeId: typeof value.analysisScopeId === "string" ? value.analysisScopeId : undefined, qualityPlanScopeId: typeof value.qualityPlanScopeId === "string" ? value.qualityPlanScopeId : undefined, projectDefinition: value.projectDefinition, projectSavedAt: typeof value.projectSavedAt === "string" ? value.projectSavedAt : undefined };
  } catch { return projectSlug(projectIdValue) === projectSlug(DEFAULT_PROJECT_NAME) ? readWorkflowState() : emptyWorkflowState(); }
}

async function writeProjectWorkflow(projectIdValue: string, state: WorkflowState): Promise<void> {
  const directory = path.dirname(projectFile(projectIdValue, "workflow.json"));
  await mkdir(directory, { recursive: true });
  await writeFile(projectFile(projectIdValue, "workflow.json"), `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
}

async function ensureProjectStore(scope: WorkspaceScope): Promise<ProjectRecord[]> {
  const existing = await readProjects();
  if (existing.length) return existing;
  const legacyState = await readWorkflowState();
  const legacyDefinition = legacyState.projectDefinition ?? { name: "Data Quality Testing - Beta", domain: "", owner: "", environment: "Development", criticality: "Tier 2 — Important", description: "", tags: "" };
  const record: ProjectRecord = { id: projectSlug(legacyDefinition.name) || scope.projectId, projectDefinition: legacyDefinition, projectSavedAt: legacyState.projectSavedAt, createdAt: new Date().toISOString() };
  await writeProjects([record]);
  await writeProjectConnections(record.id, await readSaved());
  await writeProjectWorkflow(record.id, legacyState);
  return [record];
}

function projectSummaries(projects: ProjectRecord[]): Array<ProjectRecord> {
  return projects.map((project) => ({ id: project.id, projectDefinition: project.projectDefinition, projectSavedAt: project.projectSavedAt, createdAt: project.createdAt }));
}

async function readWorkflowState(): Promise<WorkflowState> {
  try {
    const value = JSON.parse(await readFile(WORKFLOW_STATE_FILE, "utf8")) as Partial<WorkflowState>;
    return {
      workspaceGeneration: typeof value.workspaceGeneration === "number" ? value.workspaceGeneration : 0,
      tests: value.tests && typeof value.tests === "object" ? value.tests : {},
      discoveries: value.discoveries && typeof value.discoveries === "object" ? value.discoveries : {},
      discoveriesByTable: value.discoveriesByTable && typeof value.discoveriesByTable === "object" ? value.discoveriesByTable as Record<string, Record<string, DiscoveryResult>> : {},
      selectedAssets: Array.isArray(value.selectedAssets) ? value.selectedAssets.filter((item): item is string => typeof item === "string") : [],
      selectedSourceTable: value.selectedSourceTable && typeof value.selectedSourceTable === "object" ? value.selectedSourceTable as SelectedSourceTable : undefined,
      selectedSourceTables: sourceTablesFromState(value),
      sourceTableScopeId: typeof value.sourceTableScopeId === "string" ? value.sourceTableScopeId : undefined,
      analysisScopeId: typeof value.analysisScopeId === "string" ? value.analysisScopeId : undefined,
      qualityPlanScopeId: typeof value.qualityPlanScopeId === "string" ? value.qualityPlanScopeId : undefined,
      projectDefinition: value.projectDefinition,
      projectSavedAt: typeof value.projectSavedAt === "string" ? value.projectSavedAt : undefined,
    };
  } catch { return { tests: {}, discoveries: {}, selectedAssets: [] }; }
}

async function writeWorkflowState(state: WorkflowState): Promise<void> {
  await mkdir(STATE_DIR, { recursive: true });
  await writeFile(WORKFLOW_STATE_FILE, `${JSON.stringify(state, null, 2)}\n`, { mode: 0o600 });
}

type OnboardingBootstrapResponse = OnboardingBootstrap & {
  bootstrapState: "EMPTY" | "SAVED";
  workspaceGeneration: number;
  workspaceRevision: string;
};

async function runtimeSuggestions(scope: WorkspaceScope, projects: ProjectRecord[]): Promise<OnboardingBootstrapResponse> {
  const activeProject = projects.find((item) => item.id === scope.projectId) ?? projects[0];
  const [runtime, workflow, savedConnections] = await Promise.all([
    runtimeProfile(),
    readProjectWorkflow(activeProject?.id ?? scope.projectId),
    readProjectConnections(activeProject?.id ?? scope.projectId),
  ]);
  const profile = (runtime.profile ?? {}) as Record<string, unknown>;
  const hints = await runtimeHints();
  const runtimeValue = (...keys: string[]): string => keys.map((key) => value(profile[key]) || hints[key]).find(Boolean) || "";
  const envName = (preferred: unknown, ...candidates: string[]): string => value(preferred) || candidates.find((key) => hints[`${key}__present`] || hints[key]) || candidates[0] || "";
  const projectRoot = value(profile.project_root) || CANONICAL_ROOT;
  const dbtRoot = value(profile.dbt_project_dir) || path.join(RUNTIME_ROOT, "dbt");
  const dbtProfilesPath = await stat(path.join(dbtRoot, "profiles.yml")).then(() => path.join(dbtRoot, "profiles.yml")).catch(() => "");
  const fileRoot = await detectedFileRoot(profile, projectRoot);
  const dbtLabel = await dbtProjectLabel(dbtRoot);
  const now = new Date().toISOString();
  const projectDefinition = activeProject?.projectDefinition ?? workflow.projectDefinition ?? { name: DEFAULT_PROJECT_NAME, domain: "", owner: "", environment: value(profile.environment) || "development", criticality: "Tier 2 — Important", description: "", tags: "" };
  const projectSavedAt = activeProject?.projectSavedAt ?? workflow.projectSavedAt ?? (workflow.projectDefinition ? await stat(WORKFLOW_STATE_FILE).then((item) => item.mtime.toISOString()).catch(() => undefined) : undefined);
  const liveConnectionChecks = await currentConnectionChecks(scope);
  const suggestedConnections: ConnectionProfile[] = [
    { id: "runtime-postgres", name: labelFrom(runtimeValue("postgres_database", "SOURCE_POSTGRES_DB"), "PostgreSQL"), kind: "postgres", environment: "Development", source: "runtime", enabled: true, updatedAt: now, config: { authMethod: "DSN / connection URL", host: runtimeValue("postgres_host", "SOURCE_POSTGRES_HOST"), port: Number(runtimeValue("postgres_port", "SOURCE_POSTGRES_PORT")) || 5432, database: runtimeValue("postgres_database", "SOURCE_POSTGRES_DB"), user: runtimeValue("postgres_user", "SOURCE_POSTGRES_USER"), dsnEnv: envName(profile.postgres_dsn_env, "ADE_POSTGRES_DSN", "SOURCE_POSTGRES_DSN", "SOURCE_POSTGRES_CONN"), sslMode: runtimeValue("postgres_sslmode") || "prefer", schemas: runtimeValue("postgres_schema_allowlist") || "public" } },
    { id: "runtime-snowflake", name: labelFrom(runtimeValue("snowflake_database", "SNOWFLAKE_DATABASE", "ADE_SNOWFLAKE_DATABASE"), "Snowflake"), kind: "snowflake", environment: "Development", source: "runtime", enabled: true, updatedAt: now, config: { authMethod: "Username + password", account: runtimeValue("snowflake_account", "SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_ACCOUNT"), user: runtimeValue("snowflake_user", "SNOWFLAKE_USER", "ADE_SNOWFLAKE_USER"), database: runtimeValue("snowflake_database", "SNOWFLAKE_DATABASE", "ADE_SNOWFLAKE_DATABASE"), schema: runtimeValue("snowflake_schema", "SNOWFLAKE_SCHEMA", "ADE_SNOWFLAKE_SCHEMA"), warehouse: runtimeValue("snowflake_warehouse", "SNOWFLAKE_WAREHOUSE", "ADE_SNOWFLAKE_WAREHOUSE"), role: runtimeValue("snowflake_role", "SNOWFLAKE_ROLE", "ADE_SNOWFLAKE_ROLE"), passwordEnv: envName(profile.snowflake_password_env, "ADE_SNOWFLAKE_PASSWORD", "SNOWFLAKE_PASSWORD") } },
    { id: "runtime-airflow", name: airflowLabel(runtimeValue("airflow_base_url", "ADE_AIRFLOW_BASE_URL", "ADE_AIRFLOW_URL")), kind: "airflow", environment: "Development", source: "runtime", enabled: true, updatedAt: now, config: { baseUrl: runtimeValue("airflow_base_url", "ADE_AIRFLOW_BASE_URL", "ADE_AIRFLOW_URL"), version: runtimeValue("airflow_version", "ADE_AIRFLOW_VERSION"), authMethod: value(profile.airflow_auth_method) || "basic_or_token", username: runtimeValue("airflow_username", "AIRFLOW_ADMIN_USERNAME"), passwordEnv: envName(profile.airflow_password_env, "ADE_AIRFLOW_PASSWORD", "AIRFLOW_ADMIN_PASSWORD"), tokenEnv: envName(profile.airflow_token_env, "ADE_AIRFLOW_TOKEN"), dagPattern: "*" } },
    { id: "runtime-dbt", name: dbtLabel, kind: "dbt", environment: "Development", source: "runtime", enabled: true, updatedAt: now, config: { projectDir: dbtRoot, profilesPath: dbtProfilesPath, target: value(profile.dbt_target_profile) || "dev", dbtExecutable: "", manifestPath: dbtRoot ? path.join(dbtRoot, "target/manifest.json") : "", runResultsPath: dbtRoot ? path.join(dbtRoot, "target/run_results.json") : "" } },
    { id: "runtime-files", name: labelFrom(path.basename(fileRoot), "Files"), kind: "files", environment: "Development", source: "runtime", enabled: true, updatedAt: now, config: { storageType: "local", rootPath: fileRoot, includePattern: "**/*.{csv,parquet}", recursive: true } },
  ];
  const hasSavedState = Boolean(
    savedConnections.length
    || Object.keys(workflow.tests).length
    || Object.keys(workflow.discoveries).length
    || Object.keys(workflow.discoveriesByTable ?? {}).length
    || workflow.selectedAssets.length
    || workflow.selectedSourceTable
    || sourceTablesFromState(workflow).length,
  );
  return {
    bootstrapState: hasSavedState ? "SAVED" : "EMPTY",
    workspaceGeneration: workflowGeneration(workflow),
    workspaceRevision: workspaceRevision(scope, workflowGeneration(workflow)),
    project: { name: value(projectDefinition.name) || DEFAULT_PROJECT_NAME, domain: value(projectDefinition.domain), environment: value(projectDefinition.environment) || value(profile.environment) || "development", root: projectRoot },
    savedConnections: savedConnections.map((saved) => {
      const runtimeMatch = suggestedConnections.find((candidate) => candidate.id === saved.id && candidate.kind === saved.kind);
      if (!runtimeMatch || saved.source !== "runtime") return saved;
      const mergedConfig = { ...saved.config };
      // Runtime-generated defaults are safe to refresh when the detected
      // runtime has a concrete value, while manual profiles remain untouched.
      for (const [key, runtimeValue] of Object.entries(runtimeMatch.config)) {
        if (runtimeValue !== "" && runtimeValue != null) mergedConfig[key] = runtimeValue;
      }
      return { ...saved, name: saved.name || runtimeMatch.name, config: mergedConfig };
    }),
    suggestedConnections,
    // Connection health belongs to the named profile, not to a selected table.
    // Discovery remains table-scoped below, but hiding test results here made a
    // successfully verified adapter appear as NOT TESTED on this page.
    savedTests: workflow.tests,
    liveConnectionChecks: Object.fromEntries(savedConnections.map((profile) => [profile.id, liveConnectionChecks[profile.kind] ?? {
      status: "UNVERIFIED",
      detail: "No current adapter read is available",
      source: "Current adapter read",
      testedAt: new Date().toISOString(),
    }])),
    savedDiscoveries: workflow.sourceTableScopeId && workflow.sourceTableScopeId === workflow.selectedSourceTable?.id ? workflow.discoveries : {},
    savedDiscoveriesByTable: workflow.discoveriesByTable ?? {},
    selectedAssets: workflow.selectedAssets,
    selectedSourceTable: workflow.selectedSourceTable,
    selectedSourceTables: sourceTablesFromState(workflow),
    sourceTableScopeId: workflow.sourceTableScopeId,
    analysisScopeId: workflow.analysisScopeId,
    qualityPlanScopeId: workflow.qualityPlanScopeId,
    projectDefinition,
    projectSavedAt,
    currentProjectId: activeProject?.id ?? scope.projectId,
    projects: projectSummaries(projects),
  };
}

function envReference(name: string): string { return "${ENV:" + name + "}"; }

function requireEnvName(profile: ConnectionProfile, configKey: string): string {
  const name = value(profile.config[configKey]);
  if (!name) throw new Error(`${configKey} is required before this connection can be tested`);
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new Error(`${configKey} must contain a valid environment-variable name`);
  return name;
}

function warehouseConfig(profile: ConnectionProfile): Record<string, unknown> {
  if (profile.kind === "postgres") return { dsn: envReference(requireEnvName(profile, "dsnEnv")) };
  return { account: profile.config.account, user: profile.config.user, database: profile.config.database, schema: profile.config.schema, warehouse: profile.config.warehouse, role: profile.config.role, password: envReference(requireEnvName(profile, "passwordEnv")) };
}

function airflowConfig(profile: ConnectionProfile): Record<string, unknown> {
  const method = value(profile.config.authMethod);
  const tokenName = value(profile.config.tokenEnv);
  const passwordName = value(profile.config.passwordEnv);
  const validEnv = (name: string) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(name);
  if (tokenName && !validEnv(tokenName)) throw new Error("tokenEnv must contain a valid environment-variable name");
  if (passwordName && !validEnv(passwordName)) throw new Error("passwordEnv must contain a valid environment-variable name");
  if (method === "bearer" && !tokenName) throw new Error("tokenEnv is required for Airflow bearer authentication");
  if (method === "basic" && !passwordName) throw new Error("passwordEnv is required for Airflow basic authentication");
  if (method === "basic_or_token" && !tokenName && !passwordName) throw new Error("tokenEnv or passwordEnv is required for Airflow authentication");
  return {
    airflow_url: value(profile.config.baseUrl),
    airflow_version: value(profile.config.version),
    airflow_username: value(profile.config.username),
    ...(tokenName ? { airflow_token_env: tokenName } : {}),
    ...(passwordName ? { airflow_password_env: passwordName } : {}),
  };
}

function dbtExecutable(profile: ConnectionProfile, projectDir: string): string {
  const configured = value(profile.config.dbtExecutable);
  if (configured) return configured;
  const candidates: string[] = [];
  let current = projectDir;
  while (current !== path.dirname(current)) {
    candidates.push(path.join(current, ".venv/bin/dbt"));
    current = path.dirname(current);
  }
  return candidates.find((candidate) => existsSync(candidate)) || "dbt";
}

async function runDbtCoreCheck(profile: ConnectionProfile, projectDir: string, profilesDir?: string): Promise<{ executable: string; version: string; parsed: boolean }> {
  const executable = dbtExecutable(profile, projectDir);
  const options = { timeout: 15000, maxBuffer: 2 * 1024 * 1024 };
  const versionResult = await execFileAsync(executable, ["--version"], options);
  const versionOutput = `${versionResult.stdout || versionResult.stderr}`.replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, "");
  const version = versionOutput.match(/Core:\s*[\r\n]+\s*-\s*installed:\s*([^\s]+)/i)?.[1]
    || versionOutput.match(/dbt\s*=\s*([^\s]+)/i)?.[1]
    || "version reported";
  const parseArgs = ["parse", "--project-dir", projectDir, "--target", value(profile.config.target) || "dev"];
  if (profilesDir) parseArgs.push("--profiles-dir", profilesDir);
  await execFileAsync(executable, parseArgs, { ...options, timeout: 30000 });
  return { executable, version, parsed: true };
}

async function upsertWarehouse(profile: ConnectionProfile): Promise<void> {
  await mkdir(STATE_DIR, { recursive: true });
  await backend("/api/v1/connections/add", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ args: { name: profile.id, platform: profile.kind, config: warehouseConfig(profile), connection_database: CONNECTION_DB, replace: true, source: "ui-draft" }, actor_mode: "builder", environment: "dev" }) });
  await chmod(CONNECTION_DB, 0o600);
}

function includedExtensions(pattern: string): Set<string> {
  const requested = ["csv", "parquet"].filter((extension) => pattern.toLowerCase().includes(extension));
  return new Set(requested.length ? requested : ["csv", "parquet"]);
}

async function localFiles(root: string, includePattern: string): Promise<DiscoveredAsset[]> {
  const assets: DiscoveredAsset[] = [];
  const extensions = includedExtensions(includePattern);
  async function walk(directory: string): Promise<void> {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) await walk(full);
      else {
        const extension = path.extname(entry.name).slice(1).toLowerCase();
        if (extensions.has(extension)) assets.push({ id: full, connectionId: "", name: path.relative(root, full), type: extension.toUpperCase(), detail: full });
      }
    }
  }
  await walk(root);
  return assets;
}

function rows(valueToCheck: unknown): Array<Record<string, unknown>> {
  return Array.isArray(valueToCheck) ? valueToCheck as Array<Record<string, unknown>> : [];
}

function category(id: string, label: string, count: number, detail: string, unavailable = false): DiscoveryCategory {
  return { id, label, count: unavailable ? undefined : count, status: unavailable ? "UNAVAILABLE" : count ? "OBSERVED" : "EMPTY", detail };
}

function proposedLayer(profile: ConnectionProfile, asset: DiscoveredAsset): PipelineLayer {
  if (profile.kind === "postgres" || profile.kind === "files") return "Sources";
  if (profile.kind === "airflow") return "Ingestion";
  if (profile.kind === "dbt") return "Transformation";
  const type = asset.type.toLowerCase();
  if (["stage", "file format", "snowpipe", "copy load", "stream", "task"].some((token) => type.includes(token))) return "Ingestion";
  return "Targets";
}

function assetLocation(profile: ConnectionProfile, asset: DiscoveredAsset): string {
  if (profile.kind === "files") return asset.detail || value(profile.config.rootPath);
  if (profile.kind === "dbt") return asset.detail || value(profile.config.manifestPath) || value(profile.config.projectDir);
  if (profile.kind === "airflow") return `${value(profile.config.baseUrl).replace(/\/$/, "")}/dags/${encodeURIComponent(asset.name)}`;
  return [asset.catalog, asset.schema, asset.name].filter(Boolean).join(".");
}

function withEvidence(
  profile: ConnectionProfile,
  result: DiscoveryResult,
  collectionMethod: string,
  classification: "LIVE_RUNTIME" | "GENERATED_ARTIFACT" | "FILESYSTEM",
): DiscoveryResult {
  return {
    ...result,
    collectionMethod,
    assets: result.assets.map((asset) => ({
      ...asset,
      proposedLayer: proposedLayer(profile, asset),
      roleStatus: "PROPOSED",
      evidence: {
        source: result.source,
        collectedAt: result.discoveredAt,
        collectionMethod,
        classification,
        confidence: result.status === "PASS" ? "HIGH" : result.status === "UNVERIFIED" ? "LOW" : "MEDIUM",
        location: assetLocation(profile, asset),
      },
    })),
  };
}

function compact(valueToNormalize: string): string {
  return valueToNormalize.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function sourceTableAliases(sourceTable: SelectedSourceTable): Set<string> {
  const name = value(sourceTable.table).toLowerCase();
  const singular = name.endsWith("s") ? name.slice(0, -1) : name;
  return new Set([name, singular].filter(Boolean).map(compact));
}

function scopedAsset(profile: ConnectionProfile, asset: DiscoveredAsset, sourceTable: SelectedSourceTable): boolean {
  const aliases = sourceTableAliases(sourceTable);
  const name = value(asset.name);
  const normalizedName = compact(name);
  if (profile.kind === "postgres") {
    return normalizedName === compact(sourceTable.table)
      && (!sourceTable.schema || !asset.schema || value(asset.schema).toLowerCase() === value(sourceTable.schema).toLowerCase());
  }
  if (profile.kind === "snowflake") {
    // The warehouse target intentionally lives in a different database/schema;
    // correlate by the selected source table name, then show the target namespace.
    return normalizedName === compact(sourceTable.table);
  }
  if (profile.kind === "airflow") {
    const airflowAliases: Record<string, string[]> = {
      booking_channels: ["ingest_reference_data"],
      room_inventory: ["ingest_inventory"],
      stays: ["ingest_stays"],
      reservation_guests: ["ingest_reservation_guests"],
      reservations: ["ingest_reservations"],
      guests: ["ingest_guests"],
      loyalty_accounts: ["ingest_loyalty_accounts"],
      payments: ["ingest_payments"],
      refunds: ["ingest_refunds"],
      properties: ["ingest_reference_data"],
      rate_plans: ["ingest_reference_data"],
      room_types: ["ingest_reference_data"],
      rooms: ["ingest_reference_data"],
    };
    const expected = airflowAliases[value(sourceTable.table).toLowerCase()] ?? [];
    return expected.includes(name.toLowerCase()) || [...aliases].some((alias) => normalizedName.includes(alias));
  }
  if (profile.kind === "dbt") {
    return [...aliases].some((alias) => normalizedName.includes(alias));
  }
  return false;
}

function scopeDiscoveryResult(profile: ConnectionProfile, result: DiscoveryResult, sourceTable?: SelectedSourceTable): DiscoveryResult {
  if (!sourceTable) return result;
  const scopeLabel = `${sourceTable.database}.${sourceTable.schema}.${sourceTable.table}`;
  const assets = result.assets.filter((asset) => scopedAsset(profile, asset, sourceTable)).map((asset) => ({
    ...asset,
    detail: `${asset.detail || ""}${asset.detail ? " · " : ""}One-table scope: ${scopeLabel}`,
  }));
  return { ...result, detail: `${assets.length} ${profile.kind} assets in one-table scope ${scopeLabel}`, assets };
}

function columns(item: Record<string, unknown>, assetId: string) {
  return rows(item.columns).map((column, index) => ({
    id: `${assetId}:column:${value(column.name) || value(column.column_name) || index}`,
    name: value(column.name) || value(column.column_name) || `column_${index + 1}`,
    type: "Column" as const,
    detail: [value(column.data_type), column.nullable === true ? "nullable" : column.nullable === false ? "not null" : ""].filter(Boolean).join(" · "),
  }));
}

function domainRequest(args: Record<string, unknown>): RequestInit {
  return {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ args, actor_mode: "analyst", environment: "dev" }),
  };
}

async function snowflakeOperationalDiscovery(
  profile: ConnectionProfile,
  tableAssets: DiscoveredAsset[],
  liveInventory?: Record<string, unknown>,
  scoped = false,
): Promise<{ assets: DiscoveredAsset[]; categories: DiscoveryCategory[] }> {
  const database = value(profile.config.database) || value(liveInventory?.database);
  const schemaScope = value(profile.config.schema);
  const connectorArgs = { connection: profile.id, connection_database: CONNECTION_DB };
  const scopedArgs = { ...connectorArgs, ...(database && schemaScope ? { schema: `${database}.${schemaScope}` } : {}) };
  const inventoryTimeout = scoped ? 10000 : 30000;
  const operationalChecks = await Promise.allSettled([
    backend("/api/v1/snowflake-testing/pipes", domainRequest(scopedArgs), inventoryTimeout),
    backend("/api/v1/snowflake-testing/stages", domainRequest(scopedArgs), inventoryTimeout),
    backend("/api/v1/snowflake-testing/streams", domainRequest(scopedArgs), inventoryTimeout),
    backend("/api/v1/finops/history", domainRequest({ ...connectorArgs, platform: "snowflake", config: connectorArgs, days: 14, limit: 5000 }), scoped ? 10000 : 60000),
  ]);

  const resultAt = (index: number): Record<string, unknown> => operationalChecks[index]?.status === "fulfilled"
    ? operationalChecks[index].value
    : {};
  const unavailableAt = (index: number): boolean => operationalChecks[index]?.status === "rejected";
  const pipeResult = resultAt(0);
  const stageResult = resultAt(1);
  const streamResult = resultAt(2);
  const queryHistoryResult = resultAt(3);

  const extensions = (liveInventory?.extensions ?? {}) as Record<string, unknown>;
  const pipes = rows(pipeResult.pipes);
  const stages = rows(stageResult.stages);
  const streams = rows(streamResult.streams);
  const fileFormats = rows(extensions.file_formats).filter((item) => value(item.file_format_name) || value(item.name));
  const tasks = rows(extensions.tasks).filter((item) => value(item.name));
  const copyCommands = rows(queryHistoryResult.queries).filter((item) => /^\s*copy\s+into\b/i.test(value(item.query_text)));
  const operationalAssets: DiscoveredAsset[] = [
    ...stages.map((item) => ({ id: `${profile.id}:stage:${value(item.database)}:${value(item.schema)}:${value(item.name)}`, connectionId: profile.id, catalog: value(item.database), schema: value(item.schema), name: value(item.name), type: "Snowflake stage", detail: `${value(item.type) || "STAGE"}${item.directory_enabled === true ? " · directory enabled" : ""}` })),
    ...pipes.map((item) => ({ id: `${profile.id}:pipe:${value(item.database)}:${value(item.schema)}:${value(item.name)}`, connectionId: profile.id, catalog: value(item.database), schema: value(item.schema), name: value(item.name), type: "Snowpipe", detail: value(item.definition) || "Pipe definition observed" })),
    ...fileFormats.map((item) => ({ id: `${profile.id}:file-format:${database}:${value(item.file_format_schema) || value(item.schema_name)}:${value(item.file_format_name) || value(item.name)}`, connectionId: profile.id, catalog: database, schema: value(item.file_format_schema) || value(item.schema_name), name: value(item.file_format_name) || value(item.name), type: "Snowflake file format", detail: value(item.file_format_type) || value(item.type) || "File format observed" })),
    ...streams.map((item) => ({ id: `${profile.id}:stream:${value(item.database)}:${value(item.schema)}:${value(item.name)}`, connectionId: profile.id, catalog: value(item.database), schema: value(item.schema), name: value(item.name), type: "Snowflake stream", detail: item.stale === true ? "Stale" : "Current" })),
    ...tasks.map((item) => ({ id: `${profile.id}:task:${value(item.database_name)}:${value(item.schema_name)}:${value(item.name)}`, connectionId: profile.id, catalog: value(item.database_name), schema: value(item.schema_name), name: value(item.name), type: "Snowflake task", detail: value(item.state) || value(item.schedule) || "Task observed" })),
    ...copyCommands.map((item, index) => ({ id: `${profile.id}:copy-command:${value(item.query_id) || index}`, connectionId: profile.id, catalog: value(item.database) || database, schema: value(item.schema), name: value(item.query_id) || `COPY command ${index + 1}`, type: "COPY command", detail: value(item.query_text) })),
  ];

  const copyChecks = await Promise.allSettled(tableAssets.map(async (asset) => {
    const tableName = [asset.catalog || database, asset.schema, asset.name].filter(Boolean).join(".");
    return backend("/api/v1/snowflake-testing/copy-history", domainRequest({ ...connectorArgs, table_name: tableName, hours: 336, limit: 1000 }), scoped ? 10000 : 30000);
  }));
  const successfulCopyChecks = copyChecks.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
  const copyHistory: Array<Record<string, unknown>> = successfulCopyChecks.flatMap((result) => rows(result.history).map((item) => ({ ...item, target_table: result.table })));
  operationalAssets.push(...copyHistory.map((item, index) => ({
    id: `${profile.id}:copy:${value(item.target_table)}:${value(item.file_name)}:${value(item.last_load_time)}:${index}`,
    connectionId: profile.id,
    catalog: database,
    schema: value(item.pipe_schema_name),
    name: value(item.file_name) || value(item.target_table),
    type: "COPY load event",
    detail: `${value(item.status) || "UNKNOWN"} · ${Number(item.row_count ?? 0)} rows · ${value(item.last_load_time) || "time unavailable"}`,
  })));

  const failedCopyChecks = copyChecks.length - successfulCopyChecks.length;
  const categories = [
    category("tables", "Tables / views", tableAssets.length, `${tableAssets.length} catalog objects returned by Snowflake`),
    category("stages", "Stages", stages.length, stages.length ? `${stages.length} stages returned by SHOW STAGES` : unavailableAt(1) ? "SHOW STAGES was unavailable" : "SHOW STAGES returned no stages", unavailableAt(1)),
    category("file-formats", "File formats", fileFormats.length, fileFormats.length ? `${fileFormats.length} file formats observed` : "No file formats returned by the live catalog"),
    category("pipes", "Snowpipes", pipes.length, pipes.length ? `${pipes.length} pipes returned by SHOW PIPES` : unavailableAt(0) ? "SHOW PIPES was unavailable" : "SHOW PIPES returned no deployed pipes", unavailableAt(0)),
    category("copy-commands", "COPY commands", copyCommands.length, copyCommands.length ? `${copyCommands.length} executed COPY commands returned by QUERY_HISTORY` : unavailableAt(3) ? "QUERY_HISTORY was unavailable" : "No COPY commands were observed in the last 14 days", unavailableAt(3)),
    category("streams", "Streams", streams.length, streams.length ? `${streams.length} streams returned by SHOW STREAMS` : unavailableAt(2) ? "SHOW STREAMS was unavailable" : "SHOW STREAMS returned no streams", unavailableAt(2)),
    category("tasks", "Tasks", tasks.length, tasks.length ? `${tasks.length} tasks observed` : "No tasks returned by the live catalog"),
    category("copy-history", "COPY history", copyHistory.length, failedCopyChecks ? `${copyHistory.length} events observed; ${failedCopyChecks} table checks unavailable` : `${copyHistory.length} load events across ${successfulCopyChecks.length} tables in the last 14 days`, failedCopyChecks === copyChecks.length && copyChecks.length > 0),
  ];
  return { assets: operationalAssets, categories };
}

async function testProfile(profile: ConnectionProfile): Promise<ConnectionTestResult> {
  validateConnectionProfile(profile);
  const testedAt = new Date().toISOString();
  if (profile.kind === "postgres" || profile.kind === "snowflake") {
    if (profile.kind === "postgres" && !value(profile.config.dsnEnv)) throw new Error("PostgreSQL DSN environment-variable reference is required");
    if (profile.kind === "snowflake" && (!value(profile.config.account) || !value(profile.config.user) || !value(profile.config.passwordEnv))) throw new Error("Snowflake account, username, and password environment-variable reference are required");
    await upsertWarehouse(profile);
    const result = await backend("/api/v1/connections/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ args: { name: profile.id, connection_database: CONNECTION_DB }, actor_mode: "analyst", environment: "dev" }) }, 30000);
    const passed = ["PASS", "CONNECTED", "OK"].includes(value(result.status));
    return { status: passed ? "PASS" : "FAIL", detail: passed ? `${profile.name} accepted a live authenticated query` : errorText(result.reason) || errorText(result.error) || "Connection failed", source: "ADE secret-safe connection profile", testedAt, metadata: result };
  }
  if (profile.kind === "airflow") {
    if (!value(profile.config.baseUrl)) throw new Error("Airflow base URL is required");
    const result = await backend("/tools/airflow_runtime_health", domainRequest(airflowConfig(profile)), 30000);
    const failed = ["ERROR", "FAILED", "SKIP_EXTERNAL"].includes(value(result.status));
    return { status: failed ? "FAIL" : "PASS", detail: failed ? errorText(result.reason) || errorText(result.error) || "Airflow connection failed" : "Airflow health API authenticated successfully", source: "Airflow REST health API", testedAt, metadata: result };
  }
  if (profile.kind === "dbt") {
    const projectDir = safePath(profile.config.projectDir);
    const projectFile = path.join(projectDir, "dbt_project.yml");
    await stat(projectFile);
    const manifestPath = value(profile.config.manifestPath) ? safePath(profile.config.manifestPath) : path.join(projectDir, "target/manifest.json");
    let profilesDir = "";
    if (value(profile.config.profilesPath)) {
      const configuredProfiles = safePath(profile.config.profilesPath);
      const profileStat = await stat(configuredProfiles);
      profilesDir = profileStat.isDirectory() ? configuredProfiles : path.dirname(configuredProfiles);
    }
    let manifest = "not generated";
    try { await stat(manifestPath); manifest = "available"; } catch { /* fresh dbt projects may not have artifacts */ }
    const core = await runDbtCoreCheck(profile, projectDir, profilesDir || undefined);
    return { status: "PASS", detail: `dbt Core ${core.version}; project parsed; manifest ${manifest}`, source: projectFile, testedAt, metadata: { projectDir, manifestPath, profilesDir: profilesDir || undefined, executable: core.executable, parsed: core.parsed } };
  }
  if (value(profile.config.storageType) !== "local") return { status: "UNVERIFIED", detail: `${profile.config.storageType} is configurable, but its credentialed adapter is not implemented`, source: "Adapter registry", testedAt };
  const root = safePath(profile.config.rootPath);
  if (!(await stat(root)).isDirectory()) throw new Error("Configured file root is not a directory");
  const assets = await localFiles(root, value(profile.config.includePattern));
  return { status: "PASS", detail: `${assets.length} supported files are readable`, source: root, testedAt };
}

async function discoverProfile(profile: ConnectionProfile, sourceTable?: SelectedSourceTable): Promise<DiscoveryResult> {
  const discoveredAt = new Date().toISOString();
  if (profile.kind === "postgres" || profile.kind === "snowflake") {
    await upsertWarehouse(profile);
    const result = await backend(`/tools/${profile.kind}_live_inventory`, domainRequest({
      connection: profile.id,
      connection_database: CONNECTION_DB,
      ...(profile.kind === "postgres" && value(profile.config.schemas) ? { schemas: value(profile.config.schemas) } : {}),
    }), 60000);
    if (!["CONNECTED", "PASS"].includes(value(result.status))) throw new Error(errorText(result.reason) || `${profile.name} live inventory failed`);
    const objects = Array.isArray(result.objects) ? result.objects as Array<Record<string, unknown>> : [];
    const extensions = result.extensions && typeof result.extensions === "object" ? result.extensions as Record<string, unknown> : {};
    const primaryKeys = rows(extensions.primary_keys);
    const foreignKeys = rows(extensions.foreign_keys);
    const assets = objects.map((item) => {
      const id = `${profile.id}:${value(item.table_schema)}:${value(item.table_name)}`;
      const schema = value(item.table_schema);
      const name = value(item.table_name);
      const assetPrimaryKeys = primaryKeys.filter((key) => value(key.table_schema) === schema && value(key.table_name) === name).map((key) => ({ column: value(key.column_name), constraint: value(key.constraint_name) }));
      const assetForeignKeys = foreignKeys.filter((key) => value(key.table_schema) === schema && value(key.table_name) === name).map((key) => ({ column: value(key.column_name), constraint: value(key.constraint_name), referencedSchema: value(key.foreign_table_schema), referencedTable: value(key.foreign_table_name), referencedColumn: value(key.foreign_column_name) }));
      return {
        id,
        connectionId: profile.id,
        catalog: profile.kind === "snowflake" ? value(result.database) : value((result.connection as Record<string, unknown> | undefined)?.database_name),
        schema,
        name,
        type: value(item.table_type) || "table",
        detail: `${Array.isArray(item.columns) ? item.columns.length : 0} columns${assetPrimaryKeys.length ? ` · ${assetPrimaryKeys.length} primary key column${assetPrimaryKeys.length === 1 ? "" : "s"}` : ""}${assetForeignKeys.length ? ` · ${assetForeignKeys.length} foreign key${assetForeignKeys.length === 1 ? "" : "s"}` : ""}`,
        children: columns(item, id),
        ...(profile.kind === "postgres" ? { metadata: { primaryKeys: assetPrimaryKeys, foreignKeys: assetForeignKeys } } : {}),
      };
    });
    if (profile.kind === "snowflake") {
      const operational = await snowflakeOperationalDiscovery(profile, assets, result, Boolean(sourceTable));
      const allAssets = [...assets, ...operational.assets];
      return scopeDiscoveryResult(profile, withEvidence(profile, { status: "PASS", detail: `${allAssets.length} live assets; Snowflake operational inventory included`, source: `${value(result.source) || "Snowflake information_schema"} + SHOW/COPY_HISTORY/QUERY_HISTORY`, discoveredAt, assets: allAssets, categories: operational.categories }, "Authenticated Snowflake metadata queries", "LIVE_RUNTIME"), sourceTable);
    }
    return scopeDiscoveryResult(profile, withEvidence(profile, { status: "PASS", detail: `${assets.length} live objects discovered`, source: value(result.source) || "PostgreSQL information_schema", discoveredAt, assets }, "Authenticated information_schema query", "LIVE_RUNTIME"), sourceTable);
  }
  if (profile.kind === "airflow") {
    const args = airflowConfig(profile);
    const result = await backend("/tools/airflow_runtime_dags", domainRequest({ ...args, limit: 1000 }), 30000);
    const dags = Array.isArray(result.dags) ? result.dags as Array<Record<string, unknown>> : [];
    const pattern = value(profile.config.dagPattern) || "*";
    const matcher = new RegExp(`^${pattern.split("*").map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*")}$`, "i");
    const visibleDags = dags.filter((dag) => matcher.test(value(dag.dag_id)));
    const taskChecks = await Promise.allSettled(visibleDags.map((dag) => backend("/tools/airflow_runtime_tasks", domainRequest({ ...args, dag_id: value(dag.dag_id) }), 30000)));
    const assets = visibleDags.map((dag, index) => {
      const dagId = value(dag.dag_id);
      const id = `${profile.id}:${dagId}`;
      const taskResult = taskChecks[index]?.status === "fulfilled" ? taskChecks[index].value : {};
      const tasks = rows(taskResult.tasks);
      return { id, connectionId: profile.id, name: dagId, type: "Airflow DAG", detail: `${dag.is_paused === true ? "Paused" : "Active"} · ${tasks.length} tasks`, children: tasks.map((task, taskIndex) => ({ id: `${id}:task:${value(task.task_id) || taskIndex}`, name: value(task.task_id) || `task_${taskIndex + 1}`, type: "Airflow task" as const, detail: value(task.operator_name) || value(task.class_ref) || value(task.trigger_rule) })) };
    });
    return scopeDiscoveryResult(profile, withEvidence(profile, { status: "PASS", detail: `${assets.length} live DAGs and ${assets.reduce((sum, asset) => sum + (asset.children?.length ?? 0), 0)} task definitions discovered`, source: "Airflow REST API", discoveredAt, assets }, "Authenticated Airflow DAG and task API requests", "LIVE_RUNTIME"), sourceTable);
  }
  if (profile.kind === "dbt") {
    let projectDir = safePath(profile.config.projectDir);
    let manifestPath = value(profile.config.manifestPath) ? safePath(profile.config.manifestPath) : path.join(projectDir, "target/manifest.json");
    if (sourceTable) {
      const candidate = path.join(CANONICAL_ROOT, "runtime/hospitality-data-reliability-lab/dbt");
      const candidateManifest = path.join(candidate, "target/manifest.json");
      const configuredHasScope = await readFile(manifestPath, "utf8").then((content) => content.toLowerCase().includes(value(sourceTable.table).toLowerCase())).catch(() => false);
      if (!configuredHasScope && await stat(candidateManifest).then(() => true).catch(() => false)) {
        projectDir = candidate;
        manifestPath = candidateManifest;
      }
    }
    const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as { nodes?: Record<string, Record<string, unknown>>; sources?: Record<string, Record<string, unknown>> };
    const resources = [...Object.values(manifest.sources ?? {}), ...Object.values(manifest.nodes ?? {})];
    const assets = resources.map((item, index) => {
      const id = value(item.unique_id) || `${profile.id}:${index}`;
      const definedColumns = item.columns && typeof item.columns === "object" ? Object.entries(item.columns as Record<string, Record<string, unknown>>) : [];
      const originalPath = value(item.original_file_path);
      return { id, connectionId: profile.id, schema: value(item.schema), name: value(item.name), type: value(item.resource_type) || "dbt resource", detail: originalPath ? path.join(projectDir, originalPath) : manifestPath, children: definedColumns.map(([name, column], columnIndex) => ({ id: `${id}:column:${name}`, name, type: "Column" as const, detail: value(column.data_type) || value(column.description) || `manifest column ${columnIndex + 1}` })) };
    });
    return scopeDiscoveryResult(profile, withEvidence(profile, { status: "PASS", detail: `${assets.length} dbt resources parsed`, source: manifestPath, discoveredAt, assets }, "Parsed dbt manifest.json", "GENERATED_ARTIFACT"), sourceTable);
  }
  if (value(profile.config.storageType) !== "local") return withEvidence(profile, { status: "UNVERIFIED", detail: "Object-storage discovery adapter is not implemented", source: "Adapter registry", discoveredAt, assets: [] }, "No compatible object-storage adapter", "FILESYSTEM");
  const root = safePath(profile.config.rootPath);
  const assets = (await localFiles(root, value(profile.config.includePattern))).map((asset) => ({ ...asset, connectionId: profile.id }));
  return scopeDiscoveryResult(profile, withEvidence(profile, { status: "PASS", detail: `${assets.length} files discovered`, source: root, discoveredAt, assets }, "Recursive filesystem scan with extension filter", "FILESYSTEM"), sourceTable);
}

export async function GET(request: Request) {
  try {
    if (isPhase4Fixture(request)) return Response.json(phase4OnboardingWorkspace(), { headers: { "Cache-Control": "no-store", "X-ADQ-Test-Fixture": "phase4" } });
    const scope = await resolveWorkspace(request);
    const projects = await ensureProjectStore(scope);
    const activeProject = projects.find((item) => item.id === scope.projectId) ?? projects[0];
    const activeScope: WorkspaceScope = activeProject && activeProject.id !== scope.projectId
      ? { ...scope, projectId: activeProject.id, name: value(activeProject.projectDefinition.name) || scope.name, environment: (value(activeProject.projectDefinition.environment) || scope.environment).toLowerCase() }
      : scope;
    const bootstrap = await runtimeSuggestions(activeScope, projects);
    return Response.json(bootstrap, { headers: onboardingHeaders(activeScope, bootstrap.workspaceGeneration) });
  }
  catch (error) {
    return Response.json({ bootstrapState: "ERROR", error: error instanceof Error ? error.message : "Unable to load onboarding data" }, { status: 500, headers: { "Cache-Control": "no-store" } });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as { action?: string; profile?: ConnectionProfile; profiles?: ConnectionProfile[]; selectedAssets?: string[]; selectedSourceTable?: SelectedSourceTable; selectedSourceTables?: SelectedSourceTable[]; sourceTableId?: string; projectDefinition?: Record<string, string> };
    const scope = await resolveWorkspace(request);
    let projects = await ensureProjectStore(scope);
    if (body.action === "delete-project") {
      const deleted = projects.find((item) => item.id === scope.projectId);
      if (!deleted) return Response.json({ error: "Project not found" }, { status: 404 });
      if (projects.length <= 1) return Response.json({ error: "The only saved project cannot be deleted. Start and save another project first." }, { status: 409 });
      const remaining = projects.filter((item) => item.id !== deleted.id);
      await rm(path.dirname(projectFile(deleted.id, "workflow.json")), { recursive: true, force: true });
      await writeProjects(remaining);
      const nextProject = remaining[0];
      const nextScope: WorkspaceScope = { ...scope, projectId: nextProject.id, name: value(nextProject.projectDefinition.name) || "Data Quality Project", environment: (value(nextProject.projectDefinition.environment) || scope.environment).toLowerCase(), source: "persisted_project" };
      return Response.json({ status: "DELETED", deletedProjectId: deleted.id, currentProjectId: nextProject.id, projects: projectSummaries(remaining), workspace: nextScope }, { headers: workspaceCookieHeaders(nextScope) });
    }
    if (body.action === "save") {
      const previous = await readProjectConnections(scope.projectId);
      const profiles = Array.isArray(body.profiles) ? body.profiles.map(validateConnectionProfile) : [];
      const previousById = new Map(previous.map((profile) => [profile.id, profileFingerprint(profile)]));
      const changed = new Set(profiles.filter((profile) => previousById.get(profile.id) !== profileFingerprint(profile)).map((profile) => profile.id));
      await writeProjectConnections(scope.projectId, profiles);
      const state = await readProjectWorkflow(scope.projectId);
      const ids = new Set(profiles.map((item) => item.id));
      state.tests = Object.fromEntries(Object.entries(state.tests).filter(([id]) => ids.has(id) && !changed.has(id)));
      state.discoveries = Object.fromEntries(Object.entries(state.discoveries).filter(([id]) => ids.has(id) && !changed.has(id)));
      const validAssetIds = new Set(Object.values(state.discoveries).flatMap((discovery) => discovery.assets.map((asset) => asset.id)));
      state.selectedAssets = state.selectedAssets.filter((id) => validAssetIds.has(id));
      await writeProjectWorkflow(scope.projectId, state);
      return Response.json({ status: "SAVED", count: profiles.length, invalidated: [...changed] }, { headers: workspaceCookieHeaders(scope) });
    }
    if (["save-project", "create-project", "save-as-new"].includes(body.action ?? "")) {
      const definition = body.projectDefinition ?? {};
      const name = value(definition.name).trim();
      if (!name) return Response.json({ error: "Project name is required" }, { status: 400 });
      const isNew = body.action !== "save-project" || !projects.some((item) => item.id === scope.projectId);
      const baseId = projectSlug(name) || "data-quality-project";
      let targetId = isNew ? baseId : scope.projectId;
      let suffix = 2;
      while (isNew && projects.some((item) => item.id === targetId)) targetId = `${baseId}-${suffix++}`;
      const savedAt = new Date().toISOString();
      const existing = projects.find((item) => item.id === targetId);
      const targetDefinition: Record<string, string> = { ...(existing?.projectDefinition ?? {}), ...definition, name };
      const record: ProjectRecord = { id: targetId, projectDefinition: targetDefinition, projectSavedAt: savedAt, createdAt: existing?.createdAt ?? savedAt };
      projects = [...projects.filter((item) => item.id !== targetId), record];
      await writeProjects(projects);
      if (isNew) {
        await writeProjectConnections(targetId, []);
        await writeProjectWorkflow(targetId, { ...emptyWorkflowState(), projectDefinition: targetDefinition, projectSavedAt: savedAt });
      } else {
        const state = await readProjectWorkflow(targetId);
        state.projectDefinition = targetDefinition;
        state.projectSavedAt = savedAt;
        await writeProjectWorkflow(targetId, state);
      }
      const nextScope: WorkspaceScope = { ...scope, projectId: targetId, name, environment: (value(targetDefinition.environment) || scope.environment).toLowerCase(), source: "persisted_project" };
      return Response.json({ status: "SAVED", savedAt, workspace: nextScope, currentProjectId: targetId, projects: projectSummaries(projects) }, { headers: workspaceCookieHeaders(nextScope) });
    }
    if (body.action === "save-selection") {
      const state = await readProjectWorkflow(scope.projectId);
      state.selectedAssets = Array.isArray(body.selectedAssets) ? body.selectedAssets.filter((item): item is string => typeof item === "string") : [];
      await writeProjectWorkflow(scope.projectId, state);
      return Response.json({ status: "SAVED", count: state.selectedAssets.length }, { headers: workspaceCookieHeaders(scope) });
    }
    if (body.action === "save-source-table") {
      if (!body.selectedSourceTable?.id || !body.selectedSourceTable.schema || !body.selectedSourceTable.table) {
        return Response.json({ error: "A PostgreSQL source table is required." }, { status: 400 });
      }
      const state = await readProjectWorkflow(scope.projectId);
      const selectedTables = sourceTablesFromState(state);
      const nextTables = [...selectedTables.filter((item) => item.id !== body.selectedSourceTable!.id), body.selectedSourceTable];
      state.selectedSourceTable = body.selectedSourceTable;
      state.selectedSourceTables = nextTables;
      state.sourceTableScopeId = body.selectedSourceTable.id;
      state.analysisScopeId = undefined;
      state.qualityPlanScopeId = undefined;
      advanceWorkflowGeneration(state);
      await writeProjectWorkflow(scope.projectId, state);
      return Response.json({ status: "SAVED", selectedSourceTable: state.selectedSourceTable, selectedSourceTables: state.selectedSourceTables, workspaceRevision: workspaceRevision(scope, workflowGeneration(state)) }, { headers: onboardingHeaders(scope, state) });
    }
    if (body.action === "remove-source-table") {
      if (!body.sourceTableId) return Response.json({ error: "A source table id is required." }, { status: 400 });
      const state = await readProjectWorkflow(scope.projectId);
      const previousScopeId = state.sourceTableScopeId;
      const remaining = sourceTablesFromState(state).filter((item) => item.id !== body.sourceTableId);
      state.selectedSourceTables = remaining;
      state.selectedSourceTable = remaining[remaining.length - 1];
      state.sourceTableScopeId = state.selectedSourceTable?.id;
      state.analysisScopeId = undefined;
      state.qualityPlanScopeId = undefined;
      // Removing the last active table clears only the current workflow
      // selection. Discovery, plans, runs, and evidence remain persisted for
      // audit/history and can be surfaced again when a table is reselected.
      if (!remaining.length) state.selectedAssets = [];
      if (state.sourceTableScopeId !== previousScopeId) advanceWorkflowGeneration(state);
      // Discovery evidence is intentionally retained for audit/history even
      // when a table is removed from the active project selection.
      await writeProjectWorkflow(scope.projectId, state);
      return Response.json({ status: "SAVED", selectedSourceTable: state.selectedSourceTable, selectedSourceTables: remaining, workspaceRevision: workspaceRevision(scope, workflowGeneration(state)) }, { headers: onboardingHeaders(scope, state) });
    }
    if (!body.profile) return Response.json({ error: "Connection profile is required" }, { status: 400 });
    if (body.action === "test") {
      let result: ConnectionTestResult;
      try { result = await testProfile(body.profile); }
      catch (error) {
        result = { status: "FAIL", detail: error instanceof Error ? error.message : "Connection test failed", source: "Live connection test", testedAt: new Date().toISOString() };
      }
      result.metadata = { ...(result.metadata ?? {}), profileFingerprint: profileFingerprint(body.profile) };
      const state = await readProjectWorkflow(scope.projectId);
      if (state.selectedSourceTable && state.sourceTableScopeId !== state.selectedSourceTable.id) {
        state.sourceTableScopeId = state.selectedSourceTable.id;
        state.tests = {};
        state.discoveries = {};
        state.selectedAssets = [];
        advanceWorkflowGeneration(state);
      }
      state.tests[body.profile.id] = result;
      await writeProjectWorkflow(scope.projectId, state);
      return Response.json(result, { headers: onboardingHeaders(scope, state) });
    }
    if (body.action === "discover") {
      const state = await readProjectWorkflow(scope.projectId);
      const selectedTables = sourceTablesFromState(state);
      const selectedTable = selectedTables.find((item) => item.id === body.sourceTableId) ?? state.selectedSourceTable;
      if (!selectedTable) return Response.json({ error: "Add a PostgreSQL source table before discovery." }, { status: 400 });
      const testedFingerprint = value(state.tests[body.profile.id]?.metadata?.profileFingerprint);
      let result: DiscoveryResult;
      if (state.tests[body.profile.id]?.status !== "PASS" || testedFingerprint !== profileFingerprint(body.profile)) {
        result = { status: "FAIL", detail: "This exact saved connection configuration must pass Test connection before discovery", source: "Onboarding sequence guard", discoveredAt: new Date().toISOString(), assets: [] };
      } else {
        try { result = { ...validateDiscoveryEvidence(await discoverProfile(body.profile, selectedTable), body.profile.id), sourceTableId: selectedTable.id }; }
        catch (error) {
          result = { status: "FAIL", detail: error instanceof Error ? error.message : "Discovery failed", source: "Live discovery", discoveredAt: new Date().toISOString(), assets: [] };
        }
      }
      state.discoveriesByTable = state.discoveriesByTable ?? {};
      state.discoveriesByTable[selectedTable.id] = { ...(state.discoveriesByTable[selectedTable.id] ?? {}), [body.profile.id]: result };
      if (state.sourceTableScopeId === selectedTable.id) state.discoveries[body.profile.id] = result;
      await writeProjectWorkflow(scope.projectId, state);
      return Response.json(result, { headers: workspaceCookieHeaders(scope) });
    }
    return Response.json({ error: "Unsupported onboarding action" }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Onboarding operation failed" }, { status: 400 });
  }
}
