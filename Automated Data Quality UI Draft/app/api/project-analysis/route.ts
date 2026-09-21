import { readFile } from "node:fs/promises";
import path from "node:path";
import { currentWorkspaceState, hasCurrentWorkspaceAnalysis, markCurrentWorkspaceStage, projectSlug, resolveWorkspace, workspaceQuery, type WorkspaceScope } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";
const UI_ROOT = "/Users/297159/Documents/Agentic_AI/Automated Data Quality UI Draft";
const STATE_DIR = path.join(UI_ROOT, ".ade-ui");
const ONBOARDING_STATE_FILE = path.join(STATE_DIR, "onboarding-state.json");
const CONNECTIONS_FILE = path.join(STATE_DIR, "onboarding-connections.json");
const PROJECTS_DIR = path.join(STATE_DIR, "projects");

async function backend(endpoint: string, init?: RequestInit, timeoutMs = 30000): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${endpoint}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  const body = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `ADE API returned ${response.status}`);
  return body;
}

async function acceptedDiscoverySnapshot(scope: WorkspaceScope): Promise<Record<string, unknown>> {
  const projectDir = path.join(PROJECTS_DIR, projectSlug(scope.projectId) || "data-quality-project");
  const scopedWorkflow = path.join(projectDir, "workflow.json");
  const scopedConnections = path.join(projectDir, "connections.json");
  const [workflow, profiles] = await Promise.all([
    readFile(scopedWorkflow, "utf8").catch(() => readFile(ONBOARDING_STATE_FILE, "utf8")).then((value) => JSON.parse(value) as Record<string, unknown>),
    readFile(scopedConnections, "utf8").catch(() => readFile(CONNECTIONS_FILE, "utf8")).then((value) => JSON.parse(value) as Array<Record<string, unknown>>),
  ]);
  const tests = workflow.tests && typeof workflow.tests === "object" ? workflow.tests as Record<string, Record<string, unknown>> : {};
  const legacyDiscoveries = workflow.discoveries && typeof workflow.discoveries === "object" ? workflow.discoveries as Record<string, Record<string, unknown>> : {};
  const discoveriesByTable = workflow.discoveriesByTable && typeof workflow.discoveriesByTable === "object" ? workflow.discoveriesByTable as Record<string, Record<string, Record<string, unknown>>> : {};
  const selectedSourceTable = workflow.selectedSourceTable && typeof workflow.selectedSourceTable === "object" ? workflow.selectedSourceTable as Record<string, unknown> : {};
  const selectedSourceTables = Array.isArray(workflow.selectedSourceTables)
    ? workflow.selectedSourceTables.filter((item): item is Record<string, unknown> => !!item && typeof item === "object" && typeof (item as Record<string, unknown>).id === "string")
    : selectedSourceTable.id ? [selectedSourceTable] : [];
  const activeTableIds = new Set(selectedSourceTables.map((item) => String(item.id)));
  const hasActiveTableScope = activeTableIds.size > 0;
  if (!hasActiveTableScope) throw new Error("Select at least one source table before running analysis.");
  const activeTableId = String(workflow.sourceTableScopeId || selectedSourceTable.id || "");
  const discoveries: Record<string, Record<string, unknown>> = Object.fromEntries(Object.entries(legacyDiscoveries).map(([connectionId, result]) => [connectionId, {
    ...result,
    ...(activeTableId ? { sourceTableId: result.sourceTableId ?? activeTableId } : {}),
    assets: Array.isArray(result.assets)
      ? result.assets.map((asset) => asset && typeof asset === "object" && activeTableId ? { ...(asset as Record<string, unknown>), sourceTableId: (asset as Record<string, unknown>).sourceTableId ?? activeTableId } : asset)
      : result.assets,
  }]).filter(([, result]) => !hasActiveTableScope || activeTableIds.has(String((result as Record<string, unknown>).sourceTableId || activeTableId))));
  // Merge accepted discovery evidence across selected source-table scopes. The
  // old flat map remains the compatibility path for projects created earlier.
  for (const [tableId, tableResults] of Object.entries(discoveriesByTable)) {
    if (hasActiveTableScope && !activeTableIds.has(tableId)) continue;
    for (const [connectionId, result] of Object.entries(tableResults ?? {})) {
      if (!result || typeof result !== "object") continue;
      const taggedResult = {
        ...result,
        sourceTableId: result.sourceTableId ?? tableId,
        assets: Array.isArray(result.assets)
          ? result.assets.map((asset) => asset && typeof asset === "object" ? { ...(asset as Record<string, unknown>), sourceTableId: (asset as Record<string, unknown>).sourceTableId ?? tableId } : asset)
          : result.assets,
      };
      const previous = discoveries[connectionId];
      if (!previous) { discoveries[connectionId] = taggedResult; continue; }
      const assets = [...(Array.isArray(previous.assets) ? previous.assets : []), ...(Array.isArray(taggedResult.assets) ? taggedResult.assets : [])];
      discoveries[connectionId] = { ...taggedResult, assets: [...new Map(assets.filter((item) => item && typeof item === "object").map((item) => {
        const record = item as Record<string, unknown>;
        return [`${String(record.id)}:${String(record.sourceTableId || "")}`, item];
      })).values()] };
    }
  }
  // One-table onboarding is intentionally scoped to the four systems that
  // participate in the workflow. Optional file/object-storage profiles must
  // not block or pollute this analysis.
  const connections = profiles
    .filter((profile) => ["postgres", "snowflake", "airflow", "dbt"].includes(String(profile.kind)))
    .map(({ id, name, kind, environment, enabled }) => ({ id, name, kind, environment, enabled }));
  if (!connections.length) throw new Error("No saved connections are available for analysis.");
  for (const profile of connections) {
    const connectionId = String(profile.id ?? "");
    if (tests[connectionId]?.status !== "PASS" || discoveries[connectionId]?.status !== "PASS") {
      throw new Error(`Connection ${connectionId || "unknown"} must have saved passing test and discovery evidence.`);
    }
  }
  return {
    project: workflow.projectDefinition ?? null,
    connections,
    tests,
    discoveries,
    selected_assets: workflow.selectedAssets ?? [],
    source_table: workflow.selectedSourceTable ?? null,
    source_tables: selectedSourceTables,
    source_table_scope_id: workflow.sourceTableScopeId ?? null,
  };
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const currentState = await currentWorkspaceState(scope);
    if (!currentState.sourceTableScopeId) {
      return Response.json({ report: null, capabilities: { status: "NO_ACTIVE_SCOPE" }, decisions: [], workspace: scope }, { headers: { "Cache-Control": "no-store" } });
    }
    const query = workspaceQuery(scope);
    const capabilities = await backend("/api/v1/project-analysis/capabilities");
    if (!(await hasCurrentWorkspaceAnalysis(scope))) {
      return Response.json({ report: null, capabilities, decisions: [], workspace: scope }, { headers: { "Cache-Control": "no-store" } });
    }
    const decisions = await backend(`/api/v1/project-analysis/reviews?${query}`);
    const aiReview = await backend(`/api/v1/project-analysis/ai-reviews/latest?${query}`).catch(() => ({ review: null }));
    let report: Record<string, unknown> | null = null;
    try { report = await backend(`/api/v1/project-analysis/latest?${query}&view=compact`); }
    catch { /* No run exists until the operator starts analysis. */ }
      return Response.json({ report, capabilities, decisions, ai_review: aiReview.review ?? null, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load project analysis" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const body = await request.json() as { action?: string; scope?: string; review?: Record<string, unknown> };
    if (body.action === "analyze") {
      const discoverySnapshot = await acceptedDiscoverySnapshot(scope);
      const report = await backend("/api/v1/project-analysis/analyze", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ project_id: scope.projectId, environment: scope.environment, discovery_snapshot: discoverySnapshot }),
      }, 120000);
      await markCurrentWorkspaceStage(scope, "analysisScopeId");
      return Response.json({ report });
    }
    if (body.action === "refresh") {
      const discoverySnapshot = await acceptedDiscoverySnapshot(scope);
      const value = await backend("/api/v1/project-analysis/refresh", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ project_id: scope.projectId, environment: scope.environment, discovery_snapshot: discoverySnapshot }),
      }, 120000);
      await markCurrentWorkspaceStage(scope, "analysisScopeId");
      return Response.json(value);
    }
    if (body.action === "ai-verify") {
      const scopeName = typeof body.scope === "string" ? body.scope : "proposed";
      return Response.json(await backend("/api/v1/project-analysis/ai-verify", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ project_id: scope.projectId, environment: scope.environment, scope: scopeName }),
      }, 120000));
    }
    if (body.action === "review" && body.review) {
      return Response.json(await backend("/api/v1/project-analysis/reviews", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ project_id: scope.projectId, environment: scope.environment, ...body.review }),
      }));
    }
    return Response.json({ error: "Unsupported project-analysis action" }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Project analysis operation failed" }, { status: 502 });
  }
}
