export type MonitoringScope = { projectId: string; environment: string };
export type MonitoringFilters = { status: string; technology: string; asset: string; since: string; until: string; page: number };

const EMPTY_FILTERS: MonitoringFilters = { status: "", technology: "", asset: "", since: "", until: "", page: 1 };

export function monitoringScopeKey(scope: MonitoringScope): string {
  return `${encodeURIComponent(scope.projectId)}:${encodeURIComponent(scope.environment)}`;
}

export function monitoringSelectedRunKey(scope: MonitoringScope): string {
  return `ade-monitoring-selected-run:${monitoringScopeKey(scope)}`;
}

function filtersKey(scope: MonitoringScope): string {
  return `ade-monitoring-filters:${monitoringScopeKey(scope)}`;
}

function storageValue(storage: Storage | null, key: string): string | null {
  try { return storage?.getItem(key) ?? null; } catch { return null; }
}

export function readMonitoringFilters(storage: Storage | null, scope: MonitoringScope): MonitoringFilters {
  // The old unscoped key could resurrect filters from another project. It is
  // intentionally discarded and never used as a source of current scope.
  try { storage?.removeItem("ade-monitoring-filters"); } catch { /* Storage is optional. */ }
  const saved = storageValue(storage, filtersKey(scope));
  if (!saved) return { ...EMPTY_FILTERS };
  try {
    const value = JSON.parse(saved) as Partial<MonitoringFilters>;
    return {
      status: typeof value.status === "string" ? value.status : "",
      technology: typeof value.technology === "string" ? value.technology : "",
      asset: typeof value.asset === "string" ? value.asset : "",
      since: typeof value.since === "string" ? value.since : "",
      until: typeof value.until === "string" ? value.until : "",
      page: Number.isSafeInteger(value.page) && Number(value.page) > 0 ? Number(value.page) : 1,
    };
  } catch {
    try { storage?.removeItem(filtersKey(scope)); } catch { /* Storage is optional. */ }
    return { ...EMPTY_FILTERS };
  }
}

export function clearMonitoringSelection(storage: Storage | null, scope: MonitoringScope): void {
  try {
    storage?.removeItem(monitoringSelectedRunKey(scope));
    // Remove the pre-scope-key format as well so an old tab cannot restore it.
    storage?.removeItem(`ade-monitoring-selected-run:${scope.projectId}:${scope.environment}`);
  } catch { /* Storage is optional. */ }
}

export function rememberedMonitoringRun(storage: Storage | null, scope: MonitoringScope): string {
  return storageValue(storage, monitoringSelectedRunKey(scope)) || "";
}
