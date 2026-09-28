import type { SelectedSourceTable } from "./onboarding";

export type LineageScopeNode = {
  node_id: string;
  name: string;
  kind: string;
  properties: Record<string, unknown>;
};

/**
 * Scope lineage by persisted canonical table identity. Similar names such as
 * `guests` and `reservation_guests` must never be treated as the same source.
 * Untagged non-source nodes fail closed rather than being guessed into scope.
 */
export function nodeBelongsToSourceTable(
  node: LineageScopeNode,
  sourceTableId: string,
  tables: SelectedSourceTable[],
): boolean {
  if (!sourceTableId) return true;

  const directId = String(node.properties.source_table_id || node.properties.sourceTableId || "");
  const scopedIds = Array.isArray(node.properties.source_table_ids)
    ? node.properties.source_table_ids.map(String)
    : [];
  if (directId || scopedIds.length) return directId === sourceTableId || scopedIds.includes(sourceTableId);

  // Permit only the source root's exact canonical identity as a legacy
  // compatibility path. Related dbt/Airflow/warehouse nodes need explicit
  // scope metadata from accepted discovery; labels are not lineage evidence.
  if (node.kind !== "source_table") return false;
  const table = tables.find((item) => item.id === sourceTableId);
  if (!table) return false;
  const catalog = String(node.properties.catalog || node.properties.database || "");
  if (catalog && catalog.toLowerCase() !== table.database.toLowerCase()) return false;
  const schema = String(node.properties.schema || "");
  const name = String(node.properties.table || node.properties.name || "");
  if (schema || name) {
    return schema.toLowerCase() === table.schema.toLowerCase()
      && name.toLowerCase() === table.table.toLowerCase();
  }
  const exactNames = new Set([
    `${table.database}.${table.schema}.${table.table}`,
    `postgres.${table.schema}.${table.table}`,
  ].map((value) => value.toLowerCase()));
  const exactIds = new Set([
    `postgres:${table.schema}:${table.table}`,
    `${table.database}:${table.schema}:${table.table}`,
  ].map((value) => value.toLowerCase()));
  return exactNames.has(node.name.toLowerCase())
    || exactNames.has(node.node_id.toLowerCase())
    || exactIds.has(String(node.properties.discovery_asset_id || node.node_id).toLowerCase());
}
