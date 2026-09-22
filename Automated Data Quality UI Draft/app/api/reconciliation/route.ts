import { readFile } from "node:fs/promises";
import path from "node:path";
import { currentWorkspaceRunIds, currentWorkspaceState, projectSlug, recordMatchesCurrentExecution, resolveWorkspace, type WorkspaceScope } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

async function backend(endpoint: string, init?: RequestInit, timeoutMs = 120000): Promise<Record<string, unknown>> {
  const headers = new Headers(init?.headers);
  headers.set("x-ade-project-id", (init as RequestInit & { projectId?: string })?.projectId ?? "data-quality-testing-beta");
  const response = await fetch(`${API_BASE}${endpoint}`, { ...init, headers, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  const value = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : `ADE API returned ${response.status}`);
  return value;
}

function catalog(metadata: Record<string, unknown>, database = ""): Array<Record<string, unknown>> {
  const objects = Array.isArray(metadata.objects) ? metadata.objects : [];
  return objects.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const value = item as Record<string, unknown>;
    const schema = String(value.table_schema ?? value.schema ?? "");
    const table = String(value.table_name ?? value.table ?? value.name ?? "");
    if (!schema || !table) return [];
    const columns = Array.isArray(value.columns) ? value.columns.flatMap((column) => {
      if (typeof column === "string") return [column];
      if (!column || typeof column !== "object") return [];
      const columnValue = column as Record<string, unknown>;
      const name = columnValue.name ?? columnValue.column_name;
      return name ? [String(name)] : [];
    }) : [];
    return [{ database, schema, table, label: `${database ? `${database}.` : ""}${schema}.${table}`, columns }];
  });
}

async function savedCatalog(scope: WorkspaceScope, connectionId: string): Promise<{ database: string; schema: string; items: Array<Record<string, unknown>> }> {
  try {
    const root = path.join(process.cwd(), ".ade-ui", "projects", projectSlug(scope.projectId));
    const [connections, workflow] = await Promise.all([
      readFile(path.join(root, "connections.json"), "utf8").then((value) => JSON.parse(value) as Array<Record<string, unknown>>).catch(() => []),
      readFile(path.join(root, "workflow.json"), "utf8").then((value) => JSON.parse(value) as Record<string, unknown>),
    ]);
    const profile = connections.find((item) => item.id === connectionId) ?? {};
    const config = profile.config && typeof profile.config === "object" ? profile.config as Record<string, unknown> : {};
    const discoveries = workflow.discoveries && typeof workflow.discoveries === "object" ? workflow.discoveries as Record<string, unknown> : {};
    const discoveriesByTable = workflow.discoveriesByTable && typeof workflow.discoveriesByTable === "object" ? workflow.discoveriesByTable as Record<string, unknown> : {};
    const discoveryGroups = [
      discoveries[connectionId],
      ...Object.values(discoveriesByTable).flatMap((group) => group && typeof group === "object" ? [(group as Record<string, unknown>)[connectionId]] : []),
    ].filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && String((item as Record<string, unknown>).status ?? "PASS").toUpperCase() === "PASS"));
    const items = discoveryGroups.flatMap((discovery) => {
      const assets = Array.isArray(discovery.assets) ? discovery.assets : [];
      return assets.flatMap((asset) => {
        if (!asset || typeof asset !== "object") return [];
        const value = asset as Record<string, unknown>;
        const schema = String(value.schema ?? "");
        const table = String(value.name ?? "");
        const assetType = String(value.type ?? "").toLowerCase();
        if (!schema || !table || !["table", "base table"].includes(assetType)) return [];
        const children = Array.isArray(value.children) ? value.children.flatMap((child) => {
          if (!child || typeof child !== "object") return [];
          const name = (child as Record<string, unknown>).name;
          return name ? [String(name)] : [];
        }) : [];
        const assetDatabase = String(config.database ?? config.catalog ?? value.catalog ?? "");
        return [{ database: assetDatabase, schema, table, label: `${assetDatabase ? `${assetDatabase}.` : ""}${schema}.${table}`, columns: children }];
      });
    });
    const uniqueItems = [...new Map(items.map((item) => [item.label, item])).values()];
    return { database: String(config.database ?? config.catalog ?? uniqueItems[0]?.database ?? ""), schema: String(config.schema ?? config.schemas ?? ""), items: uniqueItems };
  } catch {
    return { database: "", schema: "", items: [] };
  }
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const [currentState, currentRunIds] = await Promise.all([currentWorkspaceState(scope), currentWorkspaceRunIds(scope)]);
    const hasActiveTable = Boolean(currentState.sourceTableScopeId && currentState.selectedSourceTable);
    const metadata = (endpoint: string): Promise<Record<string, unknown>> => backend(endpoint, { projectId: scope.projectId } as RequestInit & { projectId: string }, 8000).catch(() => ({ status: "UNAVAILABLE" }));
    const [history, qualityHistory, postgres, snowflake] = await Promise.all([
      backend(`/api/v1/reconciliation/history?limit=50`, { projectId: scope.projectId } as RequestInit & { projectId: string }),
      backend(`/api/v1/quality/recent?limit=100`, { projectId: scope.projectId } as RequestInit & { projectId: string }),
      metadata("/api/v1/connections/postgres/metadata"),
      metadata("/api/v1/connections/snowflake/metadata"),
    ]);
    const postgresConnection = postgres.connection && typeof postgres.connection === "object" ? postgres.connection as Record<string, unknown> : {};
    const snowflakeConnection = snowflake.connection && typeof snowflake.connection === "object" ? snowflake.connection as Record<string, unknown> : {};
    const savedPostgres = catalog(postgres, String(postgresConnection.database_name ?? postgres.database ?? ""));
    const savedSnowflake = catalog(snowflake, String(snowflakeConnection.database_name ?? snowflake.database ?? ""));
    const [postgresSnapshot, snowflakeSnapshot] = await Promise.all([savedCatalog(scope, "runtime-postgres"), savedCatalog(scope, "runtime-snowflake")]);
    const sourceCatalog = hasActiveTable ? (savedPostgres.length ? savedPostgres : postgresSnapshot.items) : [];
    const targetCatalog = hasActiveTable ? (savedSnowflake.length ? savedSnowflake : snowflakeSnapshot.items) : [];
    const historyItems = Array.isArray(history.items) ? history.items.filter((item) => recordMatchesCurrentExecution(item, currentState, currentRunIds)) : [];
    const qualityItems = Array.isArray(qualityHistory.items) ? qualityHistory.items.filter((item) => recordMatchesCurrentExecution(item, currentState, currentRunIds)) : [];
    const databases = hasActiveTable ? { source: postgresConnection.database_name ?? postgresSnapshot.database ?? "", target: snowflakeConnection.database_name ?? snowflake.database ?? snowflakeSnapshot.database ?? "" } : { source: "", target: "" };
    const schemas = hasActiveTable ? { source: postgresConnection.schema_name ?? postgresSnapshot.schema ?? "public", target: snowflakeConnection.schema_name ?? snowflakeSnapshot.schema ?? "RAW" } : { source: "", target: "" };
    return Response.json({ history: { ...history, count: historyItems.length, items: historyItems }, qualityHistory: { ...qualityHistory, count: qualityItems.length, items: qualityItems }, workspace: scope, execution: { runCount: currentRunIds.size }, databases, schemas, connectionStatus: { source: postgres.status === "CONNECTED" ? "CONNECTED" : sourceCatalog.length ? "CACHED DISCOVERY" : postgres.status ?? "UNKNOWN", target: snowflake.status === "CONNECTED" ? "CONNECTED" : targetCatalog.length ? "CACHED DISCOVERY" : snowflake.status ?? "UNKNOWN" }, catalogs: { source: sourceCatalog, target: targetCatalog } }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load reconciliation history" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const body = await request.json() as Record<string, unknown>;
    const required = ["sourceSchema", "sourceTable", "targetSchema", "targetTable"];
    if (required.some((key) => !String(body[key] ?? "").trim())) {
      return Response.json({ error: "Choose a source and target table from the populated catalog." }, { status: 400 });
    }
    const checkType = String(body.checkType ?? "ROW_COUNT").toUpperCase();
    if (["NULL", "DUPLICATE"].includes(checkType)) {
      const side = String(body.checkSide ?? "source").toLowerCase() === "target" ? "target" : "source";
      const platform = side === "target" ? "snowflake" : "postgres";
      const column = String(body.checkColumn ?? "").trim();
      if (!column) return Response.json({ error: "Choose a column for the null or duplicate check." }, { status: 400 });
      const result = await backend("/api/v1/quality/run-live", {
        method: "POST",
        projectId: scope.projectId,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ platform, schema: String(side === "target" ? body.targetSchema : body.sourceSchema), table: String(side === "target" ? body.targetTable : body.sourceTable), contract: { type: checkType === "NULL" ? "COMPLETENESS" : "UNIQUENESS", columns: [column], max_null_count: 0, max_null_percentage: 0, max_duplicate_groups: 0 } }),
      } as RequestInit & { projectId: string }, 300000);
      return Response.json({ result, checkType, checkSide: side, checkColumn: column, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
    }
    const result = await backend("/api/v1/reconciliation/live-table", {
      method: "POST",
      projectId: scope.projectId,
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        source_schema: String(body.sourceSchema),
        source_table: String(body.sourceTable),
        target_schema: String(body.targetSchema),
        target_table: String(body.targetTable),
        key_column: String(body.keyColumn ?? "").trim() || null,
        source_key_column: String(body.sourceKeyColumn ?? "").trim() || null,
        target_key_column: String(body.targetKeyColumn ?? "").trim() || null,
        max_keys: Number(body.maxKeys || 50000),
        pipeline_run_id: String(body.pipelineRunId ?? "").trim() || null,
      }),
    } as RequestInit & { projectId: string }, 300000);
    return Response.json({ result, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Reconciliation failed" }, { status: 502 });
  }
}
