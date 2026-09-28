import type { AnalysisNode } from "./project-analysis";
import type { SelectedSourceTable } from "./onboarding";

export type CatalogIdentity = {
  id?: string;
  database?: string;
  catalog?: string;
  schema?: string;
  table?: string;
  name?: string;
  label?: string;
};

export type CatalogAvailability = {
  state: "AVAILABLE" | "CACHED" | "UNAVAILABLE" | "LOADING" | "UNVERIFIED";
  /** Null means the adapter did not establish a live count. */
  availableCount: number | null;
  cachedCount: number;
};

function normalize(value: unknown): string {
  return typeof value === "string" ? value.trim().toLocaleLowerCase("en-US") : "";
}

function tableIdentity(table: CatalogIdentity): string {
  const database = normalize(table.database ?? table.catalog);
  const schema = normalize(table.schema);
  const name = normalize(table.table ?? table.name);
  if (database && schema && name) return `${database}.${schema}.${name}`;
  const label = normalize(table.label);
  if (label) return label;
  return normalize(table.id);
}

/** Canonical identity used for counts only; it never changes saved scope. */
export function uniqueSourceTables(tables: SelectedSourceTable[]): SelectedSourceTable[] {
  const unique = new Map<string, SelectedSourceTable>();
  for (const table of tables) {
    const identity = tableIdentity(table) || normalize(table.id);
    if (identity && !unique.has(identity)) unique.set(identity, table);
  }
  return [...unique.values()];
}

/** A stale/cached list is not presented as a live available catalog. */
export function catalogAvailability(items: CatalogIdentity[], status: string): CatalogAvailability {
  const count = new Set(items.map(tableIdentity).filter(Boolean)).size;
  const normalizedStatus = normalize(status).replaceAll("_", " ");
  if (["connected", "ready", "pass", "healthy", "available"].includes(normalizedStatus)) {
    return { state: "AVAILABLE", availableCount: count, cachedCount: 0 };
  }
  if (normalizedStatus.includes("loading")) return { state: "LOADING", availableCount: null, cachedCount: count };
  if (normalizedStatus.includes("cached")) return { state: "CACHED", availableCount: null, cachedCount: count };
  if (["unavailable", "error", "failed", "fail", "not configured"].some((state) => normalizedStatus.includes(state))) {
    return { state: "UNAVAILABLE", availableCount: null, cachedCount: count };
  }
  return { state: "UNVERIFIED", availableCount: null, cachedCount: count };
}

/** Count accepted graph assets once per connector, kind, namespace, and name. */
export function acceptedAssetCount(nodes: AnalysisNode[]): number {
  const identities = new Set<string>();
  for (const node of nodes) {
    const properties = node.properties ?? {};
    const technology = normalize(properties.connection_kind ?? properties.technology);
    const database = normalize(properties.catalog ?? properties.database);
    const schema = normalize(properties.schema);
    const name = normalize(node.name);
    const kind = normalize(node.kind);
    identities.add(technology && kind && name && (database || schema)
      ? `${technology}|${kind}|${database}|${schema}|${name}`
      : `node:${normalize(node.node_id)}`);
  }
  return identities.size;
}

export function analyzedFlowCount(flowIds: Array<string | null | undefined>): number {
  return new Set(flowIds.map(normalize).filter(Boolean)).size;
}

export function runtimeEvidenceCounts(runtime?: {
  observed_node_count?: unknown;
  observed_edge_count?: unknown;
  refreshed_at?: string | null;
}): { nodes: number; edges: number; refreshedAt: string | null } {
  const count = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
  return {
    nodes: count(runtime?.observed_node_count),
    edges: count(runtime?.observed_edge_count),
    refreshedAt: typeof runtime?.refreshed_at === "string" && runtime.refreshed_at ? runtime.refreshed_at : null,
  };
}

/** Report only source tables with an accepted source-table node in this analysis. */
export function sourceTableDiscoveryCoverage(
  sourceTables: SelectedSourceTable[],
  nodes: AnalysisNode[],
): { discovered: number; missing: SelectedSourceTable[] } {
  const acceptedIds = new Set<string>();
  for (const node of nodes) {
    if (node.kind !== "source_table") continue;
    const directId = node.properties.source_table_id ?? node.properties.sourceTableId;
    if (typeof directId === "string" && directId) acceptedIds.add(normalize(directId));
    const scopedIds = node.properties.source_table_ids;
    if (Array.isArray(scopedIds)) {
      for (const id of scopedIds) if (typeof id === "string" && id) acceptedIds.add(normalize(id));
    }
  }
  const uniqueTables = uniqueSourceTables(sourceTables);
  const missing = uniqueTables.filter((table) => !acceptedIds.has(normalize(table.id)));
  return { discovered: uniqueTables.length - missing.length, missing };
}
