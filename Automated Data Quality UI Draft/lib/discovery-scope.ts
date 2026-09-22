import type { DiscoveredAsset, DiscoveryResult } from "./onboarding";

export type DiscoveryResultsByTable = Record<string, Record<string, DiscoveryResult>>;

/**
 * Return only the discovery results belonging to the active source-table
 * scope. Unscoped legacy results are deliberately excluded so historical
 * inventory cannot become current workflow state.
 */
export function discoveriesForSourceTable(
  activeSourceTableId: string | undefined,
  discoveriesByTable: DiscoveryResultsByTable,
  legacyDiscoveries: Record<string, DiscoveryResult>,
): Record<string, DiscoveryResult> {
  if (!activeSourceTableId) return {};
  const scoped = discoveriesByTable[activeSourceTableId] ?? {};
  if (Object.keys(scoped).length) return scoped;
  return Object.fromEntries(
    Object.entries(legacyDiscoveries).filter(([, result]) => result.sourceTableId === activeSourceTableId),
  );
}

export function assetsForSourceTable(
  activeSourceTableId: string | undefined,
  discoveriesByTable: DiscoveryResultsByTable,
  legacyDiscoveries: Record<string, DiscoveryResult>,
): DiscoveredAsset[] {
  const results = discoveriesForSourceTable(activeSourceTableId, discoveriesByTable, legacyDiscoveries);
  return [...new Map(
    Object.values(results).flatMap((result) => result.assets).map((asset) => [asset.id, asset]),
  ).values()];
}

export function selectedAssetsForScope(selectedAssetIds: string[], scopedAssets: DiscoveredAsset[]): string[] {
  const allowed = new Set(scopedAssets.map((asset) => asset.id));
  return selectedAssetIds.filter((assetId) => allowed.has(assetId));
}
