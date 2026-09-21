import { resolveWorkspace } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

async function backend(endpoint: string, projectId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    cache: "no-store",
    headers: { "x-ade-project-id": projectId },
    signal: AbortSignal.timeout(30000),
  });
  const value = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : `ADE API returned ${response.status}`);
  return value;
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const metadata = await backend("/api/v1/connections/postgres/metadata", scope.projectId);
    const objects = Array.isArray(metadata.objects) ? metadata.objects : [];
    const tables = objects.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const value = item as Record<string, unknown>;
      const schema = String(value.table_schema ?? value.schema ?? "");
      const table = String(value.table_name ?? value.table ?? value.name ?? "");
      const tableType = String(value.table_type ?? "BASE TABLE").toUpperCase();
      if (!schema || !table || !["BASE TABLE", "TABLE"].includes(tableType)) return [];
      const columns = Array.isArray(value.columns) ? value.columns.flatMap((column) => {
        if (!column || typeof column !== "object") return [];
        const columnValue = column as Record<string, unknown>;
        const name = columnValue.name ?? columnValue.column_name;
        if (!name) return [];
        return [{ name: String(name), type: String(columnValue.data_type ?? columnValue.type ?? ""), nullable: columnValue.nullable }];
      }) : [];
      return [{ id: `postgres:${schema}:${table}`, database: String((metadata.connection as Record<string, unknown> | undefined)?.database_name ?? ""), schema, table, columns }];
    });
    return Response.json({ status: metadata.status ?? "UNKNOWN", source: metadata.source ?? "PostgreSQL metadata", tables, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load PostgreSQL source tables" }, { status: 502 });
  }
}
