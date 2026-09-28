import { readFile } from "node:fs/promises";
import path from "node:path";
import { currentWorkspaceState, projectSlug, resolveWorkspace, type WorkspaceScope } from "../../../lib/server-workspace";
import { isPhase4Fixture, phase3Reconciliation } from "../../../lib/server-test-fixture";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

async function backend(endpoint: string, init?: RequestInit, timeoutMs = 120000): Promise<Record<string, unknown>> {
  const headers = new Headers(init?.headers);
  headers.set("x-ade-project-id", (init as RequestInit & { projectId?: string })?.projectId ?? "data-quality-testing-beta");
  const environment = (init as RequestInit & { environment?: string })?.environment;
  if (environment) headers.set("x-ade-environment", environment);
  const response = await fetch(`${API_BASE}${endpoint}`, { ...init, headers, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  const value = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : `ADE API returned ${response.status} for ${endpoint}`);
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

function configuredCatalog(catalogItems: Array<Record<string, unknown>>, schemaSetting: unknown): Array<Record<string, unknown>> {
  const schemas = String(schemaSetting ?? "").split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
  if (!schemas.length) return catalogItems;
  return catalogItems.filter((item) => schemas.includes(String(item.schema ?? "").toLowerCase()));
}

function connectionState(metadata: Record<string, unknown>, catalogItems: Array<Record<string, unknown>>, profileConfigured: boolean, profileMatchesMetadata: boolean): string {
  if (!profileConfigured) return "NOT CONFIGURED";
  if (String(metadata.status ?? "").toUpperCase() === "UNAVAILABLE") return "UNAVAILABLE";
  if (!profileMatchesMetadata) return "CONFIGURATION CHANGED";
  const status = String(metadata.status ?? "UNKNOWN").toUpperCase();
  if (status === "CONNECTED") return "CONNECTED";
  if (/metadata is still being collected/i.test(String(metadata.reason ?? ""))) return "LOADING";
  return catalogItems.length ? "CACHED DISCOVERY" : status;
}

async function savedCatalog(scope: WorkspaceScope, connectionId: string): Promise<{ database: string; schema: string; items: Array<Record<string, unknown>> }> {
  try {
    const root = path.join(process.cwd(), ".ade-ui", "projects", projectSlug(scope.projectId));
    const [connections, workflow] = await Promise.all([
      readFile(path.join(root, "connections.json"), "utf8").then((value) => JSON.parse(value) as Array<Record<string, unknown>>).catch(() => []),
      readFile(path.join(root, "workflow.json"), "utf8").then((value) => JSON.parse(value) as Record<string, unknown>).catch(() => ({} as Record<string, unknown>)),
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

type ConnectionOption = { id: string; label: string; database: string; schema: string };

async function configuredConnectionOptions(scope: WorkspaceScope, kind: "postgres" | "snowflake"): Promise<ConnectionOption[]> {
  try {
    const root = path.join(process.cwd(), ".ade-ui", "projects", projectSlug(scope.projectId));
    const connections = await readFile(path.join(root, "connections.json"), "utf8").then((value) => JSON.parse(value) as Array<Record<string, unknown>>);
    return connections.flatMap((profile) => {
      if (profile.kind !== kind || profile.enabled === false || !profile.config || typeof profile.config !== "object") return [];
      const config = profile.config as Record<string, unknown>;
      const database = String(config.database ?? config.catalog ?? "").trim();
      const id = String(profile.id ?? "").trim();
      if (!database || !id) return [];
      const schema = String(config.schema ?? config.schemas ?? "").trim();
      const name = String(profile.name ?? (kind === "postgres" ? "PostgreSQL" : "Snowflake")).trim();
      return [{ id, label: `${name} · ${database}${schema ? `.${schema}` : ""}`, database, schema }];
    });
  } catch {
    return [];
  }
}

function sameDatabase(configured: string, observed: unknown): boolean {
  const actual = String(observed ?? "").trim();
  return Boolean(configured && actual && configured.localeCompare(actual, undefined, { sensitivity: "accent" }) === 0);
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    if (isPhase4Fixture(request)) return Response.json(phase3Reconciliation(), { headers: { "Cache-Control": "no-store", "X-ADQ-Test-Fixture": "phase4" } });
    const currentState = await currentWorkspaceState(scope);
    const hasActiveTable = Boolean(currentState.sourceTableScopeId && currentState.selectedSourceTable);
    const scopedInit = { projectId: scope.projectId, environment: scope.environment } as RequestInit & { projectId: string; environment: string };
    const metadata = (endpoint: string, timeoutMs = 8000): Promise<Record<string, unknown>> => backend(endpoint, scopedInit, timeoutMs).catch(() => ({ status: "UNAVAILABLE" }));
    const [historyResponse, qualityResponse, postgres, snowflake] = await Promise.all([
      backend(`/api/v1/reconciliation/history?limit=50`, scopedInit).then((value) => ({ value })).catch((error: Error) => ({ error: error.message })),
      backend(`/api/v1/quality/recent?limit=100`, scopedInit).then((value) => ({ value })).catch((error: Error) => ({ error: error.message })),
      metadata("/api/v1/connections/postgres/metadata"),
      metadata("/api/v1/connections/snowflake/metadata?catalog_only=true", 16000),
    ]);
    const history = "value" in historyResponse ? historyResponse.value : { items: [] };
    const qualityHistory = "value" in qualityResponse ? qualityResponse.value : { items: [] };
    const postgresConnection = postgres.connection && typeof postgres.connection === "object" ? postgres.connection as Record<string, unknown> : {};
    const snowflakeConnection = snowflake.connection && typeof snowflake.connection === "object" ? snowflake.connection as Record<string, unknown> : {};
    const [postgresSnapshot, snowflakeSnapshot, sourceOptions, targetOptions] = await Promise.all([
      savedCatalog(scope, "runtime-postgres"),
      savedCatalog(scope, "runtime-snowflake"),
      configuredConnectionOptions(scope, "postgres"),
      configuredConnectionOptions(scope, "snowflake"),
    ]);
    // The comparison form is itself an explicit table-selection surface.  Do
    // not require a user to first add a source table somewhere else before
    // they can see the inventories needed to make that choice.  These are
    // connector-scoped discovery results only; returning them here does not
    // alter the project's selected-source-table state or revive old runs.
    const sourceDatabase = postgresSnapshot.database;
    const targetDatabase = snowflakeSnapshot.database;
    const sourceSchema = postgresSnapshot.schema || String(postgresConnection.schema_name ?? "");
    const targetSchema = snowflakeSnapshot.schema || String(snowflakeConnection.schema_name ?? "");
    const sourceMatches = sameDatabase(sourceDatabase, postgresConnection.database_name ?? postgres.database);
    const targetMatches = sameDatabase(targetDatabase, snowflakeConnection.database_name ?? snowflake.database);
    // A profile edit invalidates the prior metadata.  We do not relabel the
    // old adapter inventory as the newly configured database; the user must
    // test the edited connection before its tables can appear here.
    const sourceCatalog = sourceMatches ? configuredCatalog(catalog(postgres, sourceDatabase), sourceSchema) : [];
    const targetCatalog = targetMatches ? configuredCatalog(catalog(snowflake, targetDatabase), targetSchema) : [];
    const matchesScope = (item: unknown, field: "result" | "details") => {
      if (!item || typeof item !== "object") return false;
      const payload = (item as Record<string, unknown>)[field];
      if (!payload || typeof payload !== "object") return false;
      const record = payload as Record<string, unknown>;
      return record.project_id === scope.projectId && String(record.environment ?? "").toLowerCase() === scope.environment;
    };
    const historyItems = Array.isArray(history.items) ? history.items.filter((item) => matchesScope(item, "result")) : [];
    const qualityItems = Array.isArray(qualityHistory.items) ? qualityHistory.items.filter((item) => matchesScope(item, "details")) : [];
    // Connection identity is useful even when no table has been selected.  The
    // table catalogs below remain empty until an explicit source-table scope
    // exists, so this never turns a configured connection into selected data.
    const databases = {
      source: sourceDatabase,
      target: targetDatabase,
    };
    const schemas = {
      source: sourceSchema,
      target: targetSchema,
    };
    const catalogState = !sourceDatabase || !targetDatabase
      ? "CONNECTION_NOT_CONFIGURED"
      : [postgres, snowflake].some((item) => String(item.status ?? "").toUpperCase() === "UNAVAILABLE")
        ? "METADATA_UNAVAILABLE"
      : !sourceMatches || !targetMatches
        ? "CONNECTION_CONFIGURATION_CHANGED"
        : hasActiveTable
          ? "SCOPED"
          : sourceCatalog.length || targetCatalog.length
            ? "DISCOVERED_NOT_SELECTED"
            : "NO_AVAILABLE_CATALOG";
    const connectionOptions = { source: sourceOptions, target: targetOptions };
    return Response.json({ history: { ...history, count: historyItems.length, items: historyItems, error: "error" in historyResponse ? historyResponse.error : undefined }, qualityHistory: { ...qualityHistory, count: qualityItems.length, items: qualityItems, error: "error" in qualityResponse ? qualityResponse.error : undefined }, workspace: scope, databases, schemas, connectionOptions, catalog_state: catalogState, connectionStatus: { source: connectionState(postgres, sourceCatalog, Boolean(sourceDatabase), sourceMatches), target: connectionState(snowflake, targetCatalog, Boolean(targetDatabase), targetMatches) }, catalogs: { source: sourceCatalog, target: targetCatalog } }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load reconciliation history" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    if (isPhase4Fixture(request)) return Response.json({ error: "Fixture mode is read-only; comparisons are not executed." }, { status: 403, headers: { "X-ADQ-Test-Fixture": "phase4" } });
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
        environment: scope.environment,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ platform, schema: String(side === "target" ? body.targetSchema : body.sourceSchema), table: String(side === "target" ? body.targetTable : body.sourceTable), contract: { type: checkType === "NULL" ? "COMPLETENESS" : "UNIQUENESS", columns: [column], max_null_count: 0, max_null_percentage: 0, max_duplicate_groups: 0 } }),
      } as RequestInit & { projectId: string }, 300000);
      return Response.json({ result, checkType, checkSide: side, checkColumn: column, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
    }
    const result = await backend("/api/v1/reconciliation/live-table", {
      method: "POST",
      projectId: scope.projectId,
      environment: scope.environment,
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        source_schema: String(body.sourceSchema),
        source_table: String(body.sourceTable),
        target_schema: String(body.targetSchema),
        target_table: String(body.targetTable),
        comparison_basis: checkType === "MINUS" ? String(body.comparisonBasis ?? "KEY") : "ROW_COUNT",
        key_column: checkType === "MINUS" ? String(body.keyColumn ?? "").trim() || null : null,
        source_key_column: checkType === "MINUS" ? String(body.sourceKeyColumn ?? "").trim() || null : null,
        target_key_column: checkType === "MINUS" ? String(body.targetKeyColumn ?? "").trim() || null : null,
        max_keys: Number(body.maxKeys || 50000),
        pipeline_run_id: String(body.pipelineRunId ?? "").trim() || null,
      }),
    } as RequestInit & { projectId: string }, 300000);
    return Response.json({ result, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Reconciliation failed" }, { status: 502 });
  }
}
