type SourceTableIdentity = { id: string; database: string; schema: string; table: string };

export function liveCatalogTableCount(status: string, count: unknown): number | null {
  if (!["CONNECTED", "READY", "PASS", "AVAILABLE"].includes(status.trim().toUpperCase())) return null;
  return typeof count === "number" && Number.isFinite(count) ? Math.max(0, Math.floor(count)) : null;
}

export function onboardedTableCount(tables: SourceTableIdentity[]): number {
  const identities = new Set<string>();
  for (const item of tables) {
    const canonical = [item.database, item.schema, item.table].map((part) => part.trim().normalize("NFKC").toLocaleLowerCase("en-US"));
    const identity = canonical.every(Boolean) ? canonical.join(".") : item.id.trim().toLocaleLowerCase("en-US");
    if (identity) identities.add(identity);
  }
  return identities.size;
}

export function runtimeIncorporationNote(input: {
  refreshedAt?: string | null;
  latestRunAt?: string | null;
  observedEdges?: number | null;
}): string {
  const refreshed = input.refreshedAt ? Date.parse(input.refreshedAt) : Number.NaN;
  const latestRun = input.latestRunAt ? Date.parse(input.latestRunAt) : Number.NaN;
  if (Number.isFinite(latestRun) && (!Number.isFinite(refreshed) || latestRun > refreshed)) {
    return `A persisted job run exists, but the lineage snapshot has not been refreshed since it (${input.latestRunAt}). Job completion alone does not prove a warehouse load or an observed lineage edge.`;
  }
  if (Number.isFinite(latestRun) && input.observedEdges === 0) {
    return "A job run exists, but no exact adapter-observed lineage edge was returned. Do not infer a load from job completion.";
  }
  if (Number.isFinite(refreshed)) return "Runtime snapshot is scoped to the active source table.";
  return "No runtime refresh is saved for this table.";
}
