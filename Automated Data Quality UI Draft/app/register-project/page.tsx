"use client";

import { Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ConnectionKind, ConnectionProfile, ConnectionTestResult, DiscoveredAsset, DiscoveryResult, OnboardingBootstrap, PipelineLayer, SelectedSourceTable } from "../../lib/onboarding";
import { connectionLabels, newConnection } from "../../lib/onboarding";
import DraftShell from "../DraftShell";
import styles from "../workflow.module.css";
import local from "./onboarding.module.css";
import { scopedApiUrl } from "../../lib/client-workspace";
import { Drawer, ProjectSelector } from "../components/ui";

type Phase = "overview" | "definition" | "connections" | "discovery" | "onboarding";
type ProjectDefinition = { name: string; domain: string; owner: string; environment: string; criticality: string; description: string; tags: string };
type SavedProject = ProjectDefinition & { id: string; savedAt?: string };
type FieldDefinition = { key: string; label: string; type?: "text" | "number" | "select"; options?: string[]; placeholder?: string; wide?: boolean };
type Notice = { tone: "success" | "error"; text: string } | null;

const lifecyclePhases = [
  { id: "definition" as const, title: "Define project", detail: "Business boundary" },
  { id: "connections" as const, title: "Connect systems", detail: "Configure and test" },
  { id: "discovery" as const, title: "Discover assets", detail: "Run and select" },
  { id: "map" as const, title: "Lineage", detail: "Evidence graph", href: "/map-flows" },
  { id: "rules" as const, title: "Define quality rules", detail: "Deterministic checks", href: "/test-plan?view=contracts" },
  { id: "review" as const, title: "Review and run", detail: "Approve and execute", href: "/test-plan?view=execution" },
];
const DEFAULT_PROJECT_NAME = "Data Quality Testing - Beta";
const EMPTY_PROJECT: ProjectDefinition = { name: DEFAULT_PROJECT_NAME, domain: "", owner: "", environment: "Development", criticality: "Tier 2 — Important", description: "", tags: "" };
const layerOrder: PipelineLayer[] = ["Sources", "Ingestion", "Transformation", "Targets"];
const layerDescriptions: Record<PipelineLayer, string> = {
  Sources: "Origin systems and source files",
  Ingestion: "Movement, loading and orchestration",
  Transformation: "dbt resources and transformation artifacts",
  Targets: "Warehouse tables and views",
};

function projectId(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "new-project";
}

function credentialReference(profile: ConnectionProfile): string {
  const keys = profile.kind === "postgres" ? ["dsnEnv"] : profile.kind === "snowflake" ? ["passwordEnv"] : profile.kind === "airflow" ? ["passwordEnv", "tokenEnv"] : [];
  if (!keys.length) return profile.kind === "dbt" ? "Filesystem path reference" : "Local storage path reference";
  return keys.map((key) => `${key}: ${String(profile.config[key] || "not set")}`).join(" · ");
}

const fields: Record<ConnectionKind, FieldDefinition[]> = {
  postgres: [{ key: "authMethod", label: "Authentication method", type: "select", options: ["DSN / connection URL"], wide: true }, { key: "host", label: "Host", placeholder: "db.company.net" }, { key: "port", label: "Port", type: "number" }, { key: "database", label: "Database" }, { key: "user", label: "Username" }, { key: "dsnEnv", label: "DSN secret environment variable", placeholder: "ADE_POSTGRES_DSN", wide: true }, { key: "sslMode", label: "SSL mode", type: "select", options: ["prefer", "require", "verify-ca", "verify-full"] }, { key: "schemas", label: "Included schemas", placeholder: "public, analytics" }],
  snowflake: [{ key: "authMethod", label: "Authentication method", type: "select", options: ["Username + password"], wide: true }, { key: "account", label: "Account" }, { key: "user", label: "Username" }, { key: "database", label: "Database" }, { key: "schema", label: "Default schema" }, { key: "warehouse", label: "Warehouse" }, { key: "role", label: "Role" }, { key: "passwordEnv", label: "Password secret environment variable", placeholder: "ADE_SNOWFLAKE_PASSWORD", wide: true }],
  airflow: [{ key: "baseUrl", label: "Airflow base URL", placeholder: "https://airflow.company.net", wide: true }, { key: "version", label: "Airflow version" }, { key: "authMethod", label: "Authentication", type: "select", options: ["basic_or_token", "basic", "bearer"] }, { key: "username", label: "Username" }, { key: "passwordEnv", label: "Password environment variable" }, { key: "tokenEnv", label: "Token environment variable" }, { key: "dagPattern", label: "DAG allowlist/pattern", placeholder: "hospitality_*" }],
  dbt: [{ key: "projectDir", label: "dbt Core project directory", wide: true }, { key: "profilesPath", label: "profiles.yml path", wide: true }, { key: "target", label: "Target name" }, { key: "dbtExecutable", label: "dbt executable (optional)", placeholder: "dbt" }, { key: "manifestPath", label: "manifest.json path", wide: true }, { key: "runResultsPath", label: "run_results.json path", wide: true }],
  files: [{ key: "storageType", label: "Storage type", type: "select", options: ["local", "s3", "azure", "gcs"] }, { key: "rootPath", label: "Root path / bucket / container", wide: true }, { key: "includePattern", label: "Include pattern", wide: true }],
};

function statusClass(status?: ConnectionTestResult["status"]): string { return status === "PASS" ? local.pass : status === "FAIL" ? local.fail : local.pending; }
function connectionStatusLabel(status?: ConnectionTestResult["status"]): string {
  if (status === "PASS") return "Connected";
  if (status === "FAIL") return "Needs attention";
  return "Not tested";
}
function testResultNotReady(result?: ConnectionTestResult): boolean { return result?.status !== "PASS"; }
function endpoint(profile: ConnectionProfile): string {
  const c = profile.config;
  if (profile.kind === "postgres") {
    const host = c.host ? `${String(c.host)}:${String(c.port || 5432)}` : "PostgreSQL endpoint";
    return c.database ? `${host} · ${String(c.database)}` : `${host} · DSN: ${String(c.dsnEnv || "not configured")}`;
  }
  if (profile.kind === "snowflake") return [c.account, c.database, c.schema].filter(Boolean).join(" · ") || `Snowflake account · ${String(c.passwordEnv || "credentials not configured")}`;
  if (profile.kind === "airflow") return String(c.baseUrl || "Not configured");
  if (profile.kind === "dbt") return String(c.projectDir || "dbt Core project not configured");
  return String(c.rootPath || "Not configured");
}
function authSummary(profile: ConnectionProfile): string {
  if (profile.kind === "postgres" || profile.kind === "snowflake" || profile.kind === "airflow") return String(profile.config.authMethod || "Authentication not selected");
  return profile.kind === "dbt" ? "Filesystem project" : String(profile.config.storageType || "Storage not selected");
}
function adapterCapabilities(profile: ConnectionProfile): string {
  if (profile.kind === "postgres") return "Catalog · schema · read-only SQL";
  if (profile.kind === "snowflake") return "Catalog · COPY/Snowpipe metadata · read-only SQL";
  if (profile.kind === "airflow") return "REST v1/v2 · DAGs · tasks · run status";
  if (profile.kind === "dbt") return "dbt Core · parse · manifest · run results";
  return "Filesystem inventory";
}
async function postOnboarding(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(scopedApiUrl("/api/onboarding"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
  const result = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : `Request failed (${response.status})`);
  return result;
}

function OrganizedAssetCatalog({ project, assets, connections, tests, selectedAssets, onSelect }: {
  project: ProjectDefinition;
  assets: DiscoveredAsset[];
  connections: ConnectionProfile[];
  tests: Record<string, ConnectionTestResult>;
  selectedAssets: string[];
  onSelect: (assetId: string, selected: boolean) => void;
}) {
  const environments = [...new Set(assets.map((asset) => connections.find((profile) => profile.id === asset.connectionId)?.environment || project.environment))].sort();
  return <div className={local.catalogRoot}>
    <header className={local.catalogRootHead}><div><span>PROJECT</span><strong>{project.name || "Untitled project"}</strong><small>{project.domain || "Business domain not specified"}</small></div><b>{assets.length} evidence-backed assets</b></header>
    {environments.map((environment) => {
      const environmentAssets = assets.filter((asset) => (connections.find((profile) => profile.id === asset.connectionId)?.environment || project.environment) === environment);
      return <section className={local.environmentGroup} key={environment}><header><div><span>ENVIRONMENT</span><h3>{environment}</h3></div><strong>{environmentAssets.length} assets</strong></header>
        <div className={local.layerGrid}>{layerOrder.map((layer) => {
          const layerAssets = environmentAssets.filter((asset) => asset.proposedLayer === layer);
          if (!layerAssets.length) return null;
          const connectionIds = [...new Set(layerAssets.map((asset) => asset.connectionId))];
          return <section className={local.layerGroup} key={layer}><header className={local.layerHead}><div><span>{layer}</span><small>{layerDescriptions[layer]}</small></div><strong>{layerAssets.length}</strong></header>
            {connectionIds.map((connectionId) => {
              const profile = connections.find((item) => item.id === connectionId);
              const connectionAssets = layerAssets.filter((asset) => asset.connectionId === connectionId);
              const types = [...new Set(connectionAssets.map((asset) => asset.type))].sort();
              return <div className={local.technologyGroup} key={connectionId}><header><div className={local.typeIcon}>{profile ? connectionLabels[profile.kind].slice(0, 2).toUpperCase() : "?"}</div><div><strong>{profile?.name || connectionId}</strong><small>{profile ? connectionLabels[profile.kind] : "Unknown connection"} · {connectionStatusLabel(tests[connectionId]?.status)}</small></div></header>
                {types.map((type) => {
                  const typeAssets = connectionAssets.filter((asset) => asset.type === type).sort((a, b) => `${a.schema || ""}.${a.name}`.localeCompare(`${b.schema || ""}.${b.name}`));
                  return <details className={local.assetTypeGroup} key={type} open={types.length <= 3}><summary><span>{type}</span><strong>{typeAssets.length}</strong></summary><div className={local.assetCards}>{typeAssets.map((asset) => {
                    const evidence = asset.evidence;
                    const selected = selectedAssets.includes(asset.id);
                    return <details className={local.assetCard} key={asset.id}><summary><input type="checkbox" aria-label={`Select ${asset.name}`} checked={selected} onClick={(event) => event.stopPropagation()} onChange={(event) => onSelect(asset.id, event.target.checked)} /><div><strong>{asset.name}</strong><small>{[asset.catalog, asset.schema].filter(Boolean).join(" / ") || asset.detail || "No namespace"}</small></div><span className={local.proposedBadge}>{asset.roleStatus ?? "PROPOSED"} {asset.proposedLayer ?? "ROLE"}</span></summary><div className={local.assetEvidence}>
                      <div><span>Project</span><strong>{project.name}</strong></div><div><span>Environment</span><strong>{environment}</strong></div><div><span>Connection</span><strong>{profile?.name || connectionId}</strong></div><div><span>Connection test</span><strong>{connectionStatusLabel(tests[connectionId]?.status)}</strong></div><div><span>Selection status</span><strong>{selected ? "Selected" : "Not selected"}</strong></div>
                      <div><span>Catalog / schema / path</span><strong>{evidence?.location || [asset.catalog, asset.schema, asset.name].filter(Boolean).join(".") || "Evidence location not recorded"}</strong></div><div><span>Asset type</span><strong>{asset.type}</strong></div><div><span>Evidence classification</span><strong>{evidence?.classification || "NOT RECORDED — RERUN DISCOVERY"}</strong></div><div><span>Evidence confidence</span><strong>{evidence?.confidence || "UNAVAILABLE"}</strong></div>
                      <div><span>Discovery source</span><strong>{evidence?.source || "Not recorded"}</strong></div><div><span>Collection method</span><strong>{evidence?.collectionMethod || "Not recorded"}</strong></div><div><span>Discovered at</span><strong>{evidence?.collectedAt ? new Date(evidence.collectedAt).toLocaleString() : "Not recorded"}</strong></div><div><span>Role / lineage status</span><strong>PROPOSED — NOT LINEAGE VERIFIED</strong></div>
                    </div>{asset.detail && <p className={local.assetDetail}>{asset.detail}</p>}{asset.children?.length ? <details className={local.childAssets}><summary>{asset.children.length} {asset.children[0]?.type === "Column" ? "columns" : "tasks"}</summary><div><div className={local.childEvidenceContext}><strong>Inherited discovery evidence</strong><span>{profile?.name || connectionId} · {connectionStatusLabel(tests[connectionId]?.status)} · {evidence?.classification || "Not recorded"} · {evidence?.confidence || "Unavailable"}</span><small>{evidence?.source || "Source not recorded"} · {evidence?.collectedAt ? new Date(evidence.collectedAt).toLocaleString() : "Time not recorded"} · Parent selection: {selected ? "Selected" : "Not selected"}</small></div>{asset.children.map((child) => <article key={child.id}><strong>{child.name}</strong><span>{child.type}</span><small>{child.detail || "Direct child metadata"}</small></article>)}</div></details> : null}</details>;
                  })}</div></details>;
                })}
              </div>;
            })}
          </section>;
        })}</div>
      </section>;
    })}
  </div>;
}

function AssetResultsTable({ assets, connections, selectedAssets, onSelect, onOpenDetails }: { assets: DiscoveredAsset[]; connections: ConnectionProfile[]; selectedAssets: string[]; onSelect: (assetId: string, selected: boolean) => void; onOpenDetails: (asset: DiscoveredAsset) => void }) {
  return <section className={local.resultsSection}><header><div><span className={styles.eyebrow}>ASSET RESULTS</span><h3>Evidence-backed inventory</h3><p>Compact rows keep the catalog scannable. Open an asset to inspect its evidence and children.</p></div><strong>{assets.length} shown</strong></header><div className={local.resultsTableWrap}><table className={local.resultsTable}><thead><tr><th>Asset</th><th>Connector</th><th>Type</th><th>Layer</th><th>Evidence</th><th>Select</th><th>Details</th></tr></thead><tbody>{assets.map((asset) => { const profile = connections.find((item) => item.id === asset.connectionId); const selected = selectedAssets.includes(asset.id); return <tr key={asset.id}><td><strong>{asset.name}</strong><small>{[asset.catalog, asset.schema].filter(Boolean).join(" / ") || asset.detail || "No namespace"}</small></td><td>{profile?.name || asset.connectionId}<small>{profile ? connectionLabels[profile.kind] : "Unknown connector"}</small></td><td>{asset.type}</td><td>{asset.proposedLayer || "Not classified"}</td><td><span className={local.evidenceTag}>{asset.evidence?.classification || "NOT RECORDED"}</span><small>{asset.evidence?.source || "Evidence unavailable"}</small></td><td><input type="checkbox" aria-label={`Select ${asset.name}`} checked={selected} onChange={(event) => onSelect(asset.id, event.target.checked)} /></td><td><button className={styles.quiet} onClick={() => onOpenDetails(asset)}>View details</button></td></tr>; })}</tbody></table>{!assets.length && <div className={local.emptyResult}>No assets match the current filters.</div>}</div></section>;
}

function AssetInspector({ asset, profile, test, selected, onSelect, onClose }: { asset: DiscoveredAsset | null; profile?: ConnectionProfile; test?: ConnectionTestResult; selected: boolean; onSelect: (selected: boolean) => void; onClose: () => void }) {
  if (!asset) return null;
  return <Drawer open title={asset.name} eyebrow="CATALOG INSPECTOR" onClose={onClose} footer={<button type="button" className={styles.secondary} onClick={onClose}>Close</button>}><p>{asset.type} · {profile ? connectionLabels[profile.kind] : "Unknown connector"}</p><div className={local.assetInspectorSummary}><div><span>Namespace</span><strong>{[asset.catalog, asset.schema].filter(Boolean).join(".") || "Not recorded"}</strong></div><div><span>Layer</span><strong>{asset.proposedLayer || "Not classified"}</strong></div><div><span>Connection</span><strong>{profile?.name || asset.connectionId}</strong></div><div><span>Connection check</span><strong>{test?.status || "NOT CHECKED"}</strong></div></div><label className={local.inspectorSelection}><input type="checkbox" checked={selected} onChange={(event) => onSelect(event.target.checked)} /> <span>Include this asset in the selected workflow</span></label><section className={local.inspectorSection}><h3>Discovery evidence</h3><dl><div><dt>Classification</dt><dd>{asset.evidence?.classification || "Not recorded"}</dd></div><div><dt>Source</dt><dd>{asset.evidence?.source || "Not recorded"}</dd></div><div><dt>Location</dt><dd>{asset.evidence?.location || [asset.catalog, asset.schema, asset.name].filter(Boolean).join(".") || "Not recorded"}</dd></div><div><dt>Confidence</dt><dd>{asset.evidence?.confidence || "Unavailable"}</dd></div><div><dt>Collected</dt><dd>{asset.evidence?.collectedAt ? new Date(asset.evidence.collectedAt).toLocaleString() : "Not recorded"}</dd></div></dl></section>{asset.detail && <section className={local.inspectorSection}><h3>Connector detail</h3><p>{asset.detail}</p></section>}{asset.children?.length ? <section className={local.inspectorSection}><h3>Child metadata <small>{asset.children.length}</small></h3><div className={local.inspectorChildren}>{asset.children.map((child) => <div key={child.id}><strong>{child.name}</strong><span>{child.type}</span><small>{child.detail || "Direct child metadata"}</small></div>)}</div></section> : null}</Drawer>;
}

type SourceTableOption = SelectedSourceTable;

function PostgresSourceTableDrilldown({ sourceTables, sourceStatus, assets, connections, tests, selectedSourceTable, selectedSourceTables, sourceTableScopeId, discoveryResultsByTable, onAddSourceTable, onAddAllSourceTables, onSelectSourceTable, onRemoveSourceTable, onDiscoverAssets, discoveryBusy }: {
  sourceTables: SourceTableOption[];
  sourceStatus: string;
  assets: DiscoveredAsset[];
  connections: ConnectionProfile[];
  tests: Record<string, ConnectionTestResult>;
  selectedSourceTable?: SourceTableOption;
  selectedSourceTables: SourceTableOption[];
  sourceTableScopeId?: string;
  discoveryResultsByTable: Record<string, Record<string, DiscoveryResult>>;
  onAddSourceTable: (table: SourceTableOption) => void;
  onAddAllSourceTables: (tables: SourceTableOption[]) => void;
  onSelectSourceTable: (table: SourceTableOption) => void;
  onRemoveSourceTable: (tableId: string) => void;
  onDiscoverAssets: () => void;
  discoveryBusy: boolean;
}) {
  const [tableId, setTableId] = useState(selectedSourceTable?.id || "");
  useEffect(() => { setTableId(selectedSourceTable?.id || ""); }, [selectedSourceTable?.id]);
  const chosen = sourceTables.find((table) => table.id === tableId) || selectedSourceTable;
  const scopeAdded = Boolean(chosen && selectedSourceTables.some((table) => table.id === chosen.id));
  const activeDiscoveries = selectedSourceTable ? (discoveryResultsByTable[selectedSourceTable.id] ?? {}) : {};
  const activeAssets = Object.values(activeDiscoveries).flatMap((item) => item.assets);
  const discoveredFor = (kind: ConnectionProfile["kind"]) => (Object.keys(activeDiscoveries).length ? activeAssets : assets).filter((asset) => connections.find((profile) => profile.id === asset.connectionId)?.kind === kind);
  const scopes: Array<{ kind: ConnectionProfile["kind"]; label: string; description: string }> = [
    { kind: "postgres", label: "Source", description: "Selected PostgreSQL table" },
    { kind: "snowflake", label: "Target", description: "Matching Snowflake table" },
    { kind: "airflow", label: "Airflow", description: "Matching ingestion workflow" },
    { kind: "dbt", label: "dbt", description: "Matching transformation models" },
  ];
  return <section className={styles.panel}><header className={styles.panelHead}><div><span className={styles.eyebrow}>DATA ONBOARDING</span><h2>Add source tables from PostgreSQL</h2><p>Add one, several, or all source tables. Each table keeps its own discovery evidence and can be run independently.</p></div><span>{sourceStatus}</span></header>
    <div className={local.sourceSectionLabel}><span>LIVE SOURCE CATALOG</span><strong>Available PostgreSQL metadata</strong><small>Availability can change when the connector is offline; it does not remove saved tables.</small></div>{!sourceTables.length ? <div className={local.empty}><strong>{selectedSourceTables.length ? "Live PostgreSQL metadata unavailable" : "No PostgreSQL tables available"}</strong><p>{selectedSourceTables.length ? `${selectedSourceTables.length} saved source table${selectedSourceTables.length === 1 ? " remains" : "s remain"} available below. Reconnect or refresh PostgreSQL metadata before adding another table.` : "The PostgreSQL metadata catalog could not be loaded. Check the saved PostgreSQL connection before adding a source table."}</p></div> : <div className={local.sourceTableChooser}><label className={styles.field}>PostgreSQL source table<select aria-label="Choose PostgreSQL source table" value={tableId} onChange={(event) => setTableId(event.target.value)}><option value="">Choose a table from the source database</option>{sourceTables.map((table) => <option value={table.id} key={table.id}>{table.database}.{table.schema}.{table.table}</option>)}</select></label><button className={styles.primary} disabled={!chosen || scopeAdded} onClick={() => chosen && onAddSourceTable(chosen)}>{scopeAdded ? "Table already added" : "Add source table"}</button><button className={styles.secondary} disabled={!sourceTables.some((table) => !selectedSourceTables.some((selected) => selected.id === table.id))} onClick={() => onAddAllSourceTables(sourceTables)}>Add all tables</button></div>}
    <div className={local.sourceSectionLabel}><span>SAVED PROJECT SCOPE</span><strong>{selectedSourceTables.length} source table{selectedSourceTables.length === 1 ? "" : "s"} saved in this project</strong><small>Saved selections and their discovery evidence remain visible even when live catalog metadata is unavailable.</small></div>
    {selectedSourceTables.length > 0 && <div className={local.selectedTablesList}>{selectedSourceTables.map((table) => <article className={table.id === selectedSourceTable?.id ? local.selectedTableActive : ""} key={table.id}><button onClick={() => onSelectSourceTable(table)}><strong>{table.schema}.{table.table}</strong><small>{table.columns.length} columns · {Object.keys(discoveryResultsByTable[table.id] ?? {}).length} connector result{Object.keys(discoveryResultsByTable[table.id] ?? {}).length === 1 ? "" : "s"}</small></button><button className={styles.quiet} aria-label={`Remove ${table.table} from selected source tables`} onClick={() => onRemoveSourceTable(table.id)}>Remove</button></article>)}</div>}
    {chosen && <div className={local.addedSourceTable}><header><div><span className={styles.eyebrow}>ACTIVE SOURCE TABLE</span><h3>{chosen.database}.{chosen.schema}.{chosen.table}</h3><p>{chosen.columns.length} columns loaded from PostgreSQL metadata.</p></div><span className={local.proposedBadge}>{scopeAdded ? "ADDED TABLE" : "NOT ADDED"}</span></header><details><summary>View source table columns</summary><div className={local.onboardingColumns}>{chosen.columns.map((column) => <span key={column.name}>{column.name}<small>{column.type || "Column"}{column.nullable === false ? " · NOT NULL" : ""}</small></span>)}</div></details></div>}
    {selectedSourceTable && <section className={local.assetDiscoveryStep}><header><div><span className={styles.eyebrow}>TABLE WORKFLOW</span><h3>Discover assets for {selectedSourceTable.schema}.{selectedSourceTable.table}</h3><p>Results are scoped to this active source table. Select another table above to work on it next.</p></div><button className={styles.primary} disabled={discoveryBusy} onClick={onDiscoverAssets}>{discoveryBusy ? "Running table workflow…" : "Run workflow for this table"}</button></header><div className={local.discoveryScopeGrid}>{scopes.map((scope) => { const found = discoveredFor(scope.kind); const sourceSelected = scope.kind === "postgres" && Boolean(selectedSourceTable); return <article key={scope.kind}><div className={local.typeIcon}>{scope.label.slice(0, 2).toUpperCase()}</div><div><strong>{scope.label}</strong><small>{scope.description}</small></div><b>{found.length ? `${found.length} found` : sourceSelected ? "Selected · discovery pending" : "Awaiting discovery"}</b>{found.length > 0 && <div className={local.scopeResults}>{found.slice(0, 5).map((asset) => <span key={asset.id}>{[asset.catalog, asset.schema, asset.name].filter(Boolean).join(".")}</span>)}</div>}</article>; })}</div></section>}
  </section>;
}

function ConnectionEditor({ profile, onCancel, onSave }: { profile: ConnectionProfile; onCancel: () => void; onSave: (profile: ConnectionProfile) => void }) {
  const [draft, setDraft] = useState(profile);
  const update = (key: string, value: string | number) => setDraft((current) => ({ ...current, source: "manual", config: { ...current.config, [key]: value } }));
  return <Drawer open title={profile.id.startsWith("new-") ? "Add connection" : "Edit connection"} eyebrow="CONNECTION PROFILE" onClose={onCancel} footer={<><button type="button" className={styles.secondary} onClick={onCancel}>Cancel</button><button type="button" className={styles.primary} onClick={() => onSave({ ...draft, id: draft.id.startsWith("new-") ? `${draft.kind}-${Date.now()}` : draft.id, updatedAt: new Date().toISOString() })}>Save connection</button></>}>
    <p>Configure access details. Credentials are environment references only.</p>
    <div className={styles.formGrid}>
      <label className={`${styles.field} ${styles.wide}`}>Connection name<input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
      <label className={styles.field}>Connection type<select value={draft.kind} onChange={(event) => { const replacement = newConnection(event.target.value as ConnectionKind); setDraft({ ...replacement, id: draft.id, name: replacement.name, source: "manual" }); }}>{Object.entries(connectionLabels).map(([kind, label]) => <option value={kind} key={kind}>{label}</option>)}</select></label>
      <label className={styles.field}>Environment<select value={draft.environment} onChange={(event) => setDraft((current) => ({ ...current, environment: event.target.value }))}><option>Development</option><option>Test</option><option>Production</option></select></label>
      {fields[draft.kind].map((field) => <label className={`${styles.field} ${field.wide ? styles.wide : ""}`} key={field.key}>{field.label}{field.type === "select" ? <select value={String(draft.config[field.key] ?? "")} onChange={(event) => update(field.key, event.target.value)}>{field.options?.map((option) => <option key={option}>{option}</option>)}</select> : <input type={field.type ?? "text"} placeholder={field.placeholder} value={String(draft.config[field.key] ?? "")} onChange={(event) => update(field.key, field.type === "number" ? Number(event.target.value) : event.target.value)} />}</label>)}
    </div>
    <div className={local.secretNote}><strong>No credentials are stored here.</strong><span>Use names such as ADE_POSTGRES_DSN. The server rejects password or token values. PostgreSQL uses the DSN reference as its authoritative test endpoint.</span></div>
  </Drawer>;
}

function ProjectOnboardingPage() {
  const searchParams = useSearchParams();
  const [phase, setPhase] = useState<Phase>("overview");
  const [bootstrap, setBootstrap] = useState<OnboardingBootstrap | null>(null);
  const [project, setProject] = useState<ProjectDefinition>(EMPTY_PROJECT);
  const [savedProject, setSavedProject] = useState<ProjectDefinition>(EMPTY_PROJECT);
  const [projects, setProjects] = useState<SavedProject[]>([]);
  const [activeProjectId, setActiveProjectId] = useState(projectId(DEFAULT_PROJECT_NAME));
  const [lastSavedAt, setLastSavedAt] = useState<string | undefined>();
  const [planStatus, setPlanStatus] = useState<string | null>(null);
  const [projectDirty, setProjectDirty] = useState(false);
  const [saveAsOpen, setSaveAsOpen] = useState(false);
  const [saveAsName, setSaveAsName] = useState("");
  const [connections, setConnections] = useState<ConnectionProfile[]>([]);
  const [editing, setEditing] = useState<ConnectionProfile | null>(null);
  const [tests, setTests] = useState<Record<string, ConnectionTestResult>>({});
  const [discoveries, setDiscoveries] = useState<Record<string, DiscoveryResult>>({});
  const [discoveriesByTable, setDiscoveriesByTable] = useState<Record<string, Record<string, DiscoveryResult>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [query, setQuery] = useState("");
  const [filterEnvironment, setFilterEnvironment] = useState("all");
  const [filterLayer, setFilterLayer] = useState("all");
  const [filterConnection, setFilterConnection] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [sourceTables, setSourceTables] = useState<SelectedSourceTable[]>([]);
  const [sourceStatus, setSourceStatus] = useState("LOADING");
  const [selectedSourceTable, setSelectedSourceTable] = useState<SelectedSourceTable | undefined>();
  const [selectedSourceTables, setSelectedSourceTables] = useState<SelectedSourceTable[]>([]);
  const [catalogAsset, setCatalogAsset] = useState<DiscoveredAsset | null>(null);

  const applyBootstrap = useCallback((result: OnboardingBootstrap) => {
    setBootstrap(result);
    setConnections(result.savedConnections ?? []);
    setTests(result.savedTests ?? {});
    setDiscoveries(result.savedDiscoveries ?? {});
    setDiscoveriesByTable(result.savedDiscoveriesByTable ?? {});
    setSelectedAssets(result.selectedAssets ?? []);
    setSelectedSourceTable(result.selectedSourceTable);
    setSelectedSourceTables(result.selectedSourceTables ?? (result.selectedSourceTable ? [result.selectedSourceTable] : []));
    const loadedProject = result.projectDefinition
      ? { ...EMPTY_PROJECT, ...result.projectDefinition }
      : { ...EMPTY_PROJECT, name: result.project.name || DEFAULT_PROJECT_NAME, domain: result.project.domain, environment: result.project.environment ? result.project.environment[0].toUpperCase() + result.project.environment.slice(1) : "Development" };
    const loadedId = result.currentProjectId || projectId(loadedProject.name);
    const serverProjects = (result.projects ?? []).map((item) => ({ ...EMPTY_PROJECT, ...item.projectDefinition, id: item.id, savedAt: item.projectSavedAt }));
    const currentRecord: SavedProject = { ...loadedProject, id: loadedId, savedAt: result.projectSavedAt };
    const nextProjects = serverProjects.length ? serverProjects : [currentRecord];
    setProjects(nextProjects);
    setActiveProjectId(loadedId);
    setProject(loadedProject);
    setSavedProject(loadedProject);
    setLastSavedAt(result.projectSavedAt);
    setProjectDirty(false);
  }, []);

  const loadProject = useCallback(async (id?: string, successMessage?: string) => {
    const query = id ? `?project_id=${encodeURIComponent(id)}` : "";
    const response = await fetch(`/api/onboarding${query}`, { cache: "no-store" });
    const result = await response.json() as OnboardingBootstrap & { error?: string };
    if (!response.ok) throw new Error(result.error || "Unable to load onboarding workspace");
    applyBootstrap(result);
    setPhase("overview");
    if (successMessage) setNotice({ tone: "success", text: successMessage });
  }, [applyBootstrap]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedPhase = params.get("phase");
    const phaseFromQuery: Phase = requestedPhase === "definition" || requestedPhase === "connections" || requestedPhase === "discovery" || requestedPhase === "onboarding" ? requestedPhase : "overview";
    loadProject(params.get("project_id") || undefined).then(() => {
      if (params.get("new") === "1") {
        const blankProject = { name: "", domain: "", owner: "", environment: "Development", criticality: "Tier 2 — Important", description: "", tags: "" };
        setProject(blankProject); setSavedProject(blankProject); setActiveProjectId("new-project"); setLastSavedAt(undefined); setProjectDirty(true); setConnections([]); setTests({}); setDiscoveries({}); setDiscoveriesByTable({}); setSelectedAssets([]); setSelectedSourceTables([]); setSelectedSourceTable(undefined); setPhase("definition"); setNotice({ tone: "success", text: "New unsaved project started. Add a name, then save it." });
      } else {
        setPhase(phaseFromQuery);
        if (params.get("saveAs") === "1") { setSaveAsName(`${project.name || "New project"} copy`); setSaveAsOpen(true); }
      }
    }).catch((error: Error) => setNotice({ tone: "error", text: error.message }));
  }, [loadProject]);
  useEffect(() => {
    const requestedPhase = searchParams.get("phase");
    if (requestedPhase === "definition" || requestedPhase === "connections" || requestedPhase === "discovery" || requestedPhase === "onboarding") {
      setPhase(requestedPhase);
    } else if (!requestedPhase) {
      setPhase("overview");
    }
  }, [searchParams]);
  useEffect(() => {
    const requestedId = searchParams.get("connection_id");
    const requestedKind = searchParams.get("connection_kind");
    if (phase !== "connections" || !connections.length || (!requestedId && !requestedKind)) return;
    const profile = connections.find((item) => item.id === requestedId || item.kind === requestedKind);
    if (!profile) return;
    setEditing(profile);
  }, [connections, phase, searchParams]);
  useEffect(() => {
    let mounted = true;
    void fetch(scopedApiUrl("/api/data-onboarding"), { cache: "no-store" }).then(async (response) => {
      const value = await response.json() as { status?: string; tables?: SelectedSourceTable[]; error?: string };
      if (!response.ok) throw new Error(value.error || "PostgreSQL catalog unavailable");
      if (mounted) { setSourceTables(value.tables ?? []); setSourceStatus(value.status || "READY"); }
    }).catch(() => { if (mounted) { setSourceTables([]); setSourceStatus("UNAVAILABLE"); } });
    return () => { mounted = false; };
  }, []);
  useEffect(() => {
    let mounted = true;
    void fetch(scopedApiUrl("/api/quality-plans"), { cache: "no-store", signal: AbortSignal.timeout(8000) }).then((response) => response.ok ? response.json() as Promise<{ plan?: { status?: string } | null }> : Promise.reject(new Error("plan unavailable"))).then((value) => { if (mounted) setPlanStatus(value.plan?.status ?? null); }).catch(() => { if (mounted) setPlanStatus(null); });
    return () => { mounted = false; };
  }, []);

  const saveConnections = useCallback(async (next: ConnectionProfile[]) => { await postOnboarding({ action: "save", profiles: next }); setConnections(next); setNotice({ tone: "success", text: `${next.length} connection profile${next.length === 1 ? "" : "s"} saved.` }); }, []);
  const importRuntime = async () => { if (!bootstrap) return; try { const existing = new Set(connections.map((item) => item.id)); await saveConnections([...connections, ...bootstrap.suggestedConnections.filter((item) => !existing.has(item.id))]); } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "Runtime import failed" }); } };
  const saveProfile = async (profile: ConnectionProfile) => { try { const next = connections.some((item) => item.id === profile.id) ? connections.map((item) => item.id === profile.id ? profile : item) : [...connections, profile]; await saveConnections(next); setTests((current) => { const copy = { ...current }; delete copy[profile.id]; return copy; }); setDiscoveries((current) => { const copy = { ...current }; delete copy[profile.id]; return copy; }); setEditing(null); } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "Connection could not be saved" }); } };
  const removeProfile = async (profileId: string) => { try { await saveConnections(connections.filter((item) => item.id !== profileId)); setTests((current) => { const copy = { ...current }; delete copy[profileId]; return copy; }); setDiscoveries((current) => { const copy = { ...current }; delete copy[profileId]; return copy; }); } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "Connection could not be removed" }); } };
  const testConnection = async (profile: ConnectionProfile) => { setBusy(`test:${profile.id}`); setNotice(null); try { const result = await postOnboarding({ action: "test", profile }) as ConnectionTestResult; setTests((current) => ({ ...current, [profile.id]: result })); } catch (error) { setTests((current) => ({ ...current, [profile.id]: { status: "FAIL", detail: error instanceof Error ? error.message : "Test failed", source: "Connection test", testedAt: new Date().toISOString() } })); } finally { setBusy(null); } };
  const runDiscovery = async (profile: ConnectionProfile, sourceTableId = selectedSourceTable?.id) => { setBusy(`discover:${profile.id}`); setNotice(null); try { const result = await postOnboarding({ action: "discover", profile, sourceTableId }) as DiscoveryResult; if (sourceTableId) setDiscoveriesByTable((current) => ({ ...current, [sourceTableId]: { ...(current[sourceTableId] ?? {}), [profile.id]: result } })); setDiscoveries((current) => ({ ...current, [profile.id]: result })); } catch (error) { const failed: DiscoveryResult = { status: "FAIL", detail: error instanceof Error ? error.message : "Discovery failed", source: "Discovery", discoveredAt: new Date().toISOString(), assets: [], sourceTableId }; if (sourceTableId) setDiscoveriesByTable((current) => ({ ...current, [sourceTableId]: { ...(current[sourceTableId] ?? {}), [profile.id]: failed } })); setDiscoveries((current) => ({ ...current, [profile.id]: failed })); } finally { setBusy(null); } };
  const activeTableIds = useMemo(() => new Set(selectedSourceTables.map((table) => table.id)), [selectedSourceTables]);
  const discoveredAssets = useMemo(() => {
    if (activeTableIds.size === 0) return [];
    const scoped = Object.entries(discoveriesByTable)
      .filter(([tableId]) => activeTableIds.has(tableId))
      .flatMap(([, results]) => Object.values(results));
    const source = scoped.length
      ? scoped
      : Object.values(discoveries).filter((item) => !item.sourceTableId || activeTableIds.has(item.sourceTableId));
    return [...new Map(source.flatMap((item) => item.assets).map((asset) => [asset.id, asset])).values()];
  }, [activeTableIds, discoveries, discoveriesByTable]);
  const assets = useMemo(() => discoveredAssets.filter((item) => {
    const profile = connections.find((connection) => connection.id === item.connectionId);
    const environment = profile?.environment || project.environment;
    const haystack = `${item.catalog} ${item.schema} ${item.name} ${item.type}`.toLowerCase();
    return (!query.trim() || haystack.includes(query.trim().toLowerCase())) && (filterEnvironment === "all" || environment === filterEnvironment) && (filterLayer === "all" || item.proposedLayer === filterLayer) && (filterConnection === "all" || item.connectionId === filterConnection) && (filterType === "all" || item.type === filterType);
  }), [connections, discoveredAssets, filterConnection, filterEnvironment, filterLayer, filterType, project.environment, query]);
  const availableEnvironments = useMemo(() => [...new Set(discoveredAssets.map((item) => connections.find((connection) => connection.id === item.connectionId)?.environment || project.environment))].sort(), [connections, discoveredAssets, project.environment]);
  const availableLayers = useMemo(() => layerOrder.filter((layer) => discoveredAssets.some((item) => item.proposedLayer === layer)), [discoveredAssets]);
  const availableConnections = useMemo(() => [...new Set(discoveredAssets.map((item) => item.connectionId))].map((id) => ({ id, profile: connections.find((connection) => connection.id === id) })).sort((a, b) => (a.profile?.name || a.id).localeCompare(b.profile?.name || b.id)), [connections, discoveredAssets]);
  const availableTypes = useMemo(() => [...new Set(discoveredAssets.map((item) => item.type))].sort(), [discoveredAssets]);
  const workflowProfiles = useMemo(() => connections.filter((profile) => ["postgres", "snowflake", "airflow", "dbt"].includes(profile.kind)), [connections]);
  const passed = workflowProfiles.filter((profile) => tests[profile.id]?.status === "PASS").length;
  const activeDiscoveries = selectedSourceTable ? (discoveriesByTable[selectedSourceTable.id] ?? discoveries) : {};
  const discoveryRuns = activeTableIds.size > 0
    ? workflowProfiles.filter((profile) => discoveries[profile.id] || Object.entries(discoveriesByTable).some(([tableId, results]) => activeTableIds.has(tableId) && results[profile.id])).length
    : 0;
  const discoveryPasses = workflowProfiles.filter((profile) => activeDiscoveries[profile.id]?.status === "PASS").length;
  const discoveredAssetCount = discoveredAssets.length;
  const updateProject = (key: keyof ProjectDefinition, value: string) => { setProject((current) => { const next = { ...current, [key]: value }; setProjectDirty(JSON.stringify(next) !== JSON.stringify(savedProject)); return next; }); };
  const persistProject = async (nextProject: ProjectDefinition, message: string, action: "save-project" | "create-project" | "save-as-new" = "save-project") => {
    try {
      const result = await postOnboarding({ action, projectDefinition: nextProject });
      const savedAt = typeof result.savedAt === "string" ? result.savedAt : new Date().toISOString();
      const targetId = typeof result.currentProjectId === "string" ? result.currentProjectId : activeProjectId;
      const nextProjects = Array.isArray(result.projects) ? (result.projects as Array<{ id: string; projectDefinition: ProjectDefinition; projectSavedAt?: string }>).map((item) => ({ ...EMPTY_PROJECT, ...item.projectDefinition, id: item.id, savedAt: item.projectSavedAt })) : projects;
      setProjects(nextProjects);
      setActiveProjectId(targetId);
      setLastSavedAt(savedAt);
      setProjectDirty(false);
      if (action === "save-project") {
        setProject(nextProject); setSavedProject(nextProject); setNotice({ tone: "success", text: message });
      } else {
        await loadProject(targetId, message);
      }
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "Project could not be saved" });
    }
  };
  const saveChanges = () => void persistProject(project, "Project changes saved.", activeProjectId === "new-project" ? "create-project" : "save-project");
  const saveAsNewProject = () => {
    const name = saveAsName.trim();
    if (!name) { setNotice({ tone: "error", text: "Enter a name for the new project." }); return; }
    void persistProject({ ...project, name }, "New project saved from the current definition.", "save-as-new");
    setSaveAsOpen(false); setSaveAsName("");
  };
  const deleteProject = async () => {
    if (activeProjectId === "new-project") {
      setNotice({ tone: "error", text: "The unsaved project has not been saved yet." });
      return;
    }
    if (projects.length <= 1) {
      setNotice({ tone: "error", text: "The only saved project cannot be deleted. Start and save another project first." });
      return;
    }
    const projectName = project.name || "this project";
    const warning = projectDirty
      ? `\"${projectName}\" has unsaved changes. Delete the project and discard them? This also removes its saved connections and discovery evidence.`
      : `Delete \"${projectName}\"? This also removes its saved connections and discovery evidence.`;
    if (!window.confirm(warning)) return;
    setBusy("delete-project");
    setNotice(null);
    try {
      const result = await postOnboarding({ action: "delete-project" });
      const nextProjectId = typeof result.currentProjectId === "string" ? result.currentProjectId : undefined;
      if (!nextProjectId) throw new Error("Project was deleted but no replacement project was returned");
      await loadProject(nextProjectId, `Deleted ${projectName}.`);
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "Project could not be deleted" });
    } finally {
      setBusy(null);
    }
  };
  const startNewProject = () => {
    if (projectDirty && !window.confirm("This project has unsaved changes. Start a new project without saving them?")) return;
    const blankProject = { name: "", domain: "", owner: "", environment: "Development", criticality: "Tier 2 — Important", description: "", tags: "" };
    setProject(blankProject); setSavedProject(blankProject); setActiveProjectId("new-project"); setLastSavedAt(undefined); setProjectDirty(true); setConnections([]); setTests({}); setDiscoveries({}); setDiscoveriesByTable({}); setSelectedAssets([]); setSelectedSourceTables([]); setSelectedSourceTable(undefined); setEditing(null); setPhase("definition"); setNotice({ tone: "success", text: "New unsaved project started. Add a name, then save it." });
  };
  const switchProject = (id: string) => {
    const next = projects.find((item) => item.id === id);
    if (!next) return;
    if (projectDirty && !window.confirm("This project has unsaved changes. Switch without saving them?")) return;
    void loadProject(next.id, `Loaded ${next.name}.` ).catch((error: Error) => setNotice({ tone: "error", text: error.message }));
  };
  const connectionReady = workflowProfiles.length === 4 && workflowProfiles.every((profile) => tests[profile.id]?.status === "PASS");
  const discoveryReady = connectionReady && workflowProfiles.every((profile) => activeDiscoveries[profile.id]?.status === "PASS" && (activeDiscoveries[profile.id]?.assets.length ?? 0) > 0);
  const mappingReady = discoveryReady && selectedAssets.length > 0 && Boolean(bootstrap?.analysisScopeId && bootstrap.analysisScopeId === bootstrap.sourceTableScopeId);
  const qualityPlanReady = mappingReady && Boolean(bootstrap?.qualityPlanScopeId && bootstrap.qualityPlanScopeId === bootstrap.sourceTableScopeId) && Boolean(planStatus && !["NOT_GENERATED", "NOT_RUN"].includes(planStatus.toUpperCase()));
  const updateSelection = (assetId: string, selected: boolean) => {
    const next = selected ? [...new Set([...selectedAssets, assetId])] : selectedAssets.filter((id) => id !== assetId);
    setSelectedAssets(next);
    void postOnboarding({ action: "save-selection", selectedAssets: next }).catch((error: Error) => setNotice({ tone: "error", text: error.message }));
  };
  const addSourceTable = async (table: SelectedSourceTable) => {
    setSelectedSourceTable(table);
    try {
      await postOnboarding({ action: "save-source-table", selectedSourceTable: table });
      setSelectedSourceTables((current) => [...current.filter((item) => item.id !== table.id), table]);
        setBootstrap((current) => current ? { ...current, sourceTableScopeId: table.id, selectedSourceTable: table, selectedSourceTables: [...(current.selectedSourceTables ?? []).filter((item) => item.id !== table.id), table], analysisScopeId: undefined, qualityPlanScopeId: undefined } : current);
        setNotice({ tone: "success", text: `${table.schema}.${table.table} was added. Existing table evidence was preserved.` });
    } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "Source table could not be added" }); }
  };
  const addAllSourceTables = (tables: SelectedSourceTable[]) => { void (async () => { for (const table of tables) if (!selectedSourceTables.some((item) => item.id === table.id)) await addSourceTable(table); })(); };
  const selectSourceTable = (table: SelectedSourceTable) => { setSelectedSourceTable(table); void postOnboarding({ action: "save-source-table", selectedSourceTable: table }).catch((error: Error) => setNotice({ tone: "error", text: error.message })); };
  const removeSourceTable = (tableId: string) => { const remaining = selectedSourceTables.filter((table) => table.id !== tableId); const next = remaining[remaining.length - 1]; void postOnboarding({ action: "remove-source-table", sourceTableId: tableId }).then(() => { setSelectedSourceTables(remaining); setSelectedSourceTable(next); if (!remaining.length) setSelectedAssets([]); setNotice({ tone: "success", text: remaining.length ? "Table removed from the active UI selection. Stored discovery evidence was retained." : "No source table is selected. Stored discovery evidence was retained." }); }).catch((error: Error) => setNotice({ tone: "error", text: error.message })); };
  const discoverSelectedAssets = async () => {
    if (!selectedSourceTable) return;
    if (workflowProfiles.length !== 4) {
      setNotice({ tone: "error", text: "Configure one PostgreSQL, Snowflake, Airflow, and dbt connection before running this workflow." });
      return;
    }
      setBusy("workflow-onboarding"); setNotice(null);
    try {
      for (const profile of workflowProfiles) {
        const result = await postOnboarding({ action: "test", profile }) as ConnectionTestResult;
        setTests((state) => ({ ...state, [profile.id]: result }));
        if (result.status !== "PASS") throw new Error(`${profile.name}: ${result.detail}`);
      }
      const workflowDiscoveries: Record<string, DiscoveryResult> = {};
      for (const profile of workflowProfiles) {
        const result = await postOnboarding({ action: "discover", profile, sourceTableId: selectedSourceTable.id }) as DiscoveryResult;
        workflowDiscoveries[profile.id] = result;
        setDiscoveries((state) => ({ ...state, [profile.id]: result }));
        setDiscoveriesByTable((state) => ({ ...state, [selectedSourceTable.id]: { ...(state[selectedSourceTable.id] ?? {}), [profile.id]: result } }));
        if (result.status !== "PASS" || result.assets.length === 0) throw new Error(`${profile.name}: ${result.detail || "No assets were returned for this table."}`);
      }
      const assetIds = Object.values(workflowDiscoveries).flatMap((result) => result.assets.map((asset) => asset.id));
      await postOnboarding({ action: "save-selection", selectedAssets: assetIds });
      setSelectedAssets((current) => [...new Set([...current, ...assetIds])]);
      const analysisResponse = await fetch(scopedApiUrl("/api/project-analysis"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "analyze" }) });
      const analysisBody = await analysisResponse.json() as Record<string, unknown>;
      if (!analysisResponse.ok) throw new Error(typeof analysisBody.error === "string" ? analysisBody.error : "Project analysis failed");
      setBootstrap((state) => state ? { ...state, analysisScopeId: selectedSourceTable.id } : state);
      const planResponse = await fetch(scopedApiUrl("/api/quality-plans"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "generate" }) });
      const planBody = await planResponse.json() as { plan?: Record<string, unknown>; error?: string };
      if (!planResponse.ok) throw new Error(planBody.error || "Quality plan generation failed");
      setPlanStatus(typeof planBody.plan?.status === "string" ? planBody.plan.status : "GENERATED");
      setBootstrap((state) => state ? { ...state, analysisScopeId: selectedSourceTable.id, qualityPlanScopeId: selectedSourceTable.id } : state);
      setNotice({ tone: "success", text: `One-table workflow ready: metadata, discovery, lineage analysis, mapping, and quality plan completed for ${selectedSourceTable.database}.${selectedSourceTable.schema}.${selectedSourceTable.table}.` });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "One-table workflow failed" });
    } finally { setBusy(null); }
  };

  const nextAction = !connectionReady ? "Test every configured connection" : !discoveryReady ? "Run discovery for every passing connection" : !mappingReady ? "Complete evidence-backed mapping for the selected assets" : !qualityPlanReady ? "Generate and review the deterministic quality plan" : "Approve and run the quality plan — no execution evidence exists yet";
  const activePhaseCount = [Boolean(project.name.trim()), connections.length > 0, discoveryRuns > 0, discoveryReady, mappingReady, qualityPlanReady].filter(Boolean).length;

  let content: ReactNode;
  if (phase === "overview") content = <div className={local.overviewStack}>
    <section className={styles.panel}><header className={styles.panelHead}><div><span className={styles.eyebrow}>PROJECT OVERVIEW</span><h2>{project.name || "New data-quality project"}</h2><p>Monitor readiness and move through the project lifecycle from one place.</p></div><span>{qualityPlanReady ? "READY FOR REVIEW" : "ACTION NEEDED"}</span></header>
      <div className={styles.statusCardGrid}>
        <article className={styles.statusCard}><div className={styles.statusCardHeader}><span>Project definition</span><span className={`${styles.statusPill} ${project.name && project.owner ? styles.statusGood : styles.statusWarn}`}>{project.name && project.owner ? "READY" : "ACTION"}</span></div><strong>{project.name && project.owner ? "Complete" : "Needs attention"}</strong><small>{project.name && project.owner ? "Required business information is present." : "Add a project name and accountable owner."}</small><div className={styles.statusCardFooter}><span>Phase 1</span><button className={styles.quiet} onClick={() => setPhase("definition")}>Open definition →</button></div></article>
        <article className={styles.statusCard}><div className={styles.statusCardHeader}><span>Connections</span><span className={`${styles.statusPill} ${connections.length === 0 ? styles.statusNeutral : connectionReady ? styles.statusGood : styles.statusWarn}`}>{connections.length === 0 ? "NOT CHECKED" : connectionReady ? "READY" : "ACTION"}</span></div><strong>{connections.length ? `${passed} of ${connections.length} verified` : "Not checked"}</strong><small>{connections.length ? "Every connection must pass before discovery can be complete." : "Add or import a connection before checking reachability."}</small><div className={styles.statusCardFooter}><span>Phase 2</span><button className={styles.quiet} onClick={() => setPhase("connections")}>Open connections →</button></div></article>
        <article className={styles.statusCard}><div className={styles.statusCardHeader}><span>Discovery</span><span className={`${styles.statusPill} ${discoveryReady ? styles.statusGood : styles.statusNeutral}`}>{discoveryReady ? "READY" : "IN PROGRESS"}</span></div><strong>{discoveredAssetCount} assets found</strong><small>{discoveryRuns} discovery run{discoveryRuns === 1 ? "" : "s"} across {connections.length} configured connection{connections.length === 1 ? "" : "s"}.</small><div className={styles.statusCardFooter}><span>Phase 3</span><button className={styles.quiet} onClick={() => setPhase("discovery")}>Open discovery →</button></div></article>
        <article className={styles.statusCard}><div className={styles.statusCardHeader}><span>Next action</span><span className={`${styles.statusPill} ${qualityPlanReady ? styles.statusGood : styles.statusWarn}`}>{qualityPlanReady ? "REVIEW" : "ACTION"}</span></div><strong>{qualityPlanReady ? "Review and run" : "Continue setup"}</strong><small>{nextAction}.</small><div className={styles.statusCardFooter}><span>Lifecycle</span><span>Use the steps at left</span></div></article>
      </div>
    </section>
    <section className={styles.panel}><header className={styles.panelHead}><div><h2>Project lifecycle</h2><p>Each phase opens the focused workspace for that part of the project.</p></div><span>{activePhaseCount} of 6 active</span></header><div className={local.lifecycleSummary}><div><strong>Next required action</strong><span>{nextAction}</span></div><div><strong>Evidence status</strong><span>{discoveredAssetCount ? `${discoveredAssetCount} assets are backed by discovery evidence.` : "No discovery evidence has been collected yet."}</span></div></div></section>
    <section className={styles.panel}><header className={styles.panelHead}><div><h2>Recent project activity</h2><p>Saved project events and evidence changes for the selected project.</p></div></header><ul className={local.activityList}><li><span>Project definition saved</span><time>{lastSavedAt ? new Date(lastSavedAt).toLocaleString() : "Not yet"}</time></li><li><span>{discoveryRuns ? `Discovery completed across ${discoveryRuns} connection${discoveryRuns === 1 ? "" : "s"}` : "Discovery not run yet"}</span><time>{discoveryRuns ? "Evidence available" : "Awaiting action"}</time></li><li><span>{selectedAssets.length ? `${selectedAssets.length} asset${selectedAssets.length === 1 ? "" : "s"} selected for mapping` : "No assets selected for mapping"}</span><time>{selectedAssets.length ? "Selection saved" : "Awaiting action"}</time></li></ul></section>
  </div>;
  else if (phase === "definition") content = <section className={styles.panel}><header className={styles.panelHead}><div><h2>Define project</h2><p>Describe the business boundary and runtime context.</p></div><span>EDITABLE</span></header>
    <div className={local.formSection}><div className={local.formSectionHead}><h3>Business information</h3><span>Who and what this project covers</span></div><div className={styles.formGrid}>
      <label className={styles.field}>Project name <b className={local.required}>Required</b><input value={project.name} onChange={(event) => updateProject("name", event.target.value)} /></label><label className={styles.field}>Business domain<input value={project.domain} onChange={(event) => updateProject("domain", event.target.value)} /></label><label className={styles.field}>Owner <b className={local.required}>Required</b><input value={project.owner} placeholder="Accountable team or owner" onChange={(event) => updateProject("owner", event.target.value)} /></label><label className={`${styles.field} ${styles.wide}`}>Description<textarea value={project.description} onChange={(event) => updateProject("description", event.target.value)} /></label><label className={styles.field}>Tags<input value={project.tags} placeholder="hospitality, revenue" onChange={(event) => updateProject("tags", event.target.value)} /></label>
    </div></div>
    <div className={local.formSection}><div className={local.formSectionHead}><h3>Runtime settings</h3><span>Where this project is evaluated</span></div><div className={styles.formGrid}>
      <label className={styles.field}>Environment <b className={local.required}>Required</b><select value={project.environment} onChange={(event) => updateProject("environment", event.target.value)}><option>Development</option><option>Test</option><option>Production</option></select></label><label className={styles.field}>Criticality<select value={project.criticality} onChange={(event) => updateProject("criticality", event.target.value)}><option>Tier 1 — Business critical</option><option>Tier 2 — Important</option><option>Tier 3 — Standard</option></select></label>
    </div></div>
    <div className={projectDirty ? local.unsavedStatus : local.savedStatus}><span>{projectDirty ? "●" : "✓"}</span><div><strong>{projectDirty ? "Unsaved changes" : "All changes saved"}</strong><small>{projectDirty ? "Save changes before switching projects or leaving this definition." : `Last saved ${lastSavedAt ? new Date(lastSavedAt).toLocaleString() : "not yet recorded"}.`}</small></div></div>
  </section>;
  else if (phase === "connections") content = <div className={styles.sectionStack}><section className={styles.panel}><header className={styles.panelHead}><div><h2>Connect systems</h2><p>Configure and test named profiles. A passing connection proves reachability, not lineage or data quality.</p></div><div className={styles.toolbar}><button className={styles.secondary} onClick={importRuntime} disabled={!bootstrap}>Import detected runtime</button><button className={styles.primary} onClick={() => setEditing({ ...newConnection("postgres"), id: `new-${Date.now()}` })}>+ Add connection</button></div></header>
    {!connections.length ? <div className={local.empty}><strong>No connections configured</strong><p>Add a connection to verify a system and begin discovery.</p><button className={styles.primary} onClick={() => setEditing(newConnection("postgres"))}>Add connection</button></div> : <div className={local.connectionTableWrap} role="region" aria-label="Configured connections. Scroll to view all connection actions." tabIndex={0}><table className={local.connectionTable}><thead><tr><th>Connection</th><th>Adapter</th><th>Environment</th><th>Connection check</th><th>Last checked</th><th>Actions</th></tr></thead><tbody>{connections.map((profile) => { const result = tests[profile.id]; return <tr key={profile.id}><td data-label="Connection"><button className={local.connectionName} onClick={() => setEditing(profile)}><strong>{profile.name}</strong><small>{endpoint(profile)}</small></button>{result?.status === "FAIL" && <span className={local.failureReason}>{result.detail}</span>}</td><td data-label="Adapter"><strong>{connectionLabels[profile.kind]}</strong><small className={local.adapterDetail}>{adapterCapabilities(profile)}</small></td><td data-label="Environment">{profile.environment}</td><td data-label="Connection check"><span className={`${local.status} ${statusClass(result?.status)}`}>{connectionStatusLabel(result?.status)}</span></td><td data-label="Last checked">{result ? new Date(result.testedAt).toLocaleString() : "Not checked"}</td><td data-label="Actions"><div className={local.tableActions}><button className={styles.quiet} onClick={() => setEditing(profile)}>Edit</button><button className={styles.secondary} disabled={busy !== null} onClick={() => void testConnection(profile)}>{busy === `test:${profile.id}` ? "Testing…" : "Test"}</button><button className={styles.secondary} disabled={testResultNotReady(result) || busy !== null} title={testResultNotReady(result) ? "Test this connection successfully first" : "Run discovery for this connection"} onClick={() => { setPhase("discovery"); void runDiscovery(profile); }}>{busy === `discover:${profile.id}` ? "Discovering…" : "Discover"}</button><button className={styles.quiet} onClick={() => void removeProfile(profile.id)}>Remove</button></div></td></tr>; })}</tbody></table></div>}
  </section></div>;
  else if (phase === "discovery") content = <div className={`${styles.sectionStack} ${local.discoveryPage}`}>
    <section className={`${styles.panel} ${local.discoveryPanel}`}>
      <header className={`${styles.panelHead} ${local.discoveryHead}`}>
        <div><span className={styles.eyebrow}>LIVE INVENTORY</span><h2>Discover assets</h2><p>Run discovery against a passing connection. Every result below is returned by the selected connector and carries its collection evidence.</p></div>
        <div className={local.discoveryHeadMeta}><span>{discoveryPasses}/{connections.length} discovered</span><span>{assets.length} VISIBLE ASSETS</span></div>
      </header>
      <div className={local.discoverySummary} aria-label="Discovery summary">
        <article><span>Connections</span><strong>{connections.length}</strong><small>{passed} passing tests</small></article>
        <article><span>Discovery runs</span><strong>{discoveryRuns}</strong><small>{discoveryPasses} returned assets</small></article>
        <article><span>Assets found</span><strong>{discoveredAssetCount}</strong><small>{query ? `${assets.length} match filter` : "Across all runs"}</small></article>
        <article><span>Selected</span><strong>{selectedAssets.length}</strong><small>Ready for asset roles</small></article>
      </div>
      {!connections.length ? <div className={local.empty}><strong>No connections configured</strong><p>Configure and test a connection before starting discovery.</p></div> : <details className={local.diagnosticDetails}><summary>Connector diagnostics <span>{connections.length} connectors · expand to test or rediscover</span></summary><div className={local.discoveryConnections}>{connections.map((profile) => {
        const test = tests[profile.id];
        const discovery = activeDiscoveries[profile.id];
        return <article key={profile.id} className={local.discoveryConnection}>
          <header className={local.discoveryCardHead}>
            <div className={local.discoveryIdentity}><div className={local.typeIcon}>{connectionLabels[profile.kind].slice(0, 2).toUpperCase()}</div><div><strong>{profile.name}</strong><small>{connectionLabels[profile.kind]} · {endpoint(profile)}</small></div></div>
            <div className={local.discoveryStatusRow}><span className={`${local.status} ${statusClass(test?.status)}`}>{connectionStatusLabel(test?.status)}</span><span className={`${local.status} ${statusClass(discovery?.status)}`}>{busy === `discover:${profile.id}` ? "Discovery in progress" : discovery?.status === "PASS" ? "Discovery completed" : discovery?.status === "FAIL" ? "Discovery failed" : "Discovery not run"}</span></div>
          </header>
          <div className={local.discoveryMeta}><span>Environment <strong>{profile.environment}</strong></span><span>Authentication <strong>{authSummary(profile)}</strong></span><span>Last discovery <strong>{discovery ? new Date(discovery.discoveredAt).toLocaleString() : "Not run"}</strong></span><span>Assets found <strong>{discovery ? discovery.assets.length : "—"}</strong></span></div>
          {discovery && <div className={`${local.discoveryDetail} ${discovery.status === "PASS" ? local.discoveryDetailPass : discovery.status === "FAIL" ? local.discoveryDetailFail : ""}`}><strong>{discovery.detail}</strong><small>Observed from {discovery.source} · {new Date(discovery.discoveredAt).toLocaleString()}</small></div>}
          <button className={`${styles.secondary} ${local.discoveryAction}`} disabled={test?.status !== "PASS" || busy !== null} onClick={() => void runDiscovery(profile)}>{busy === `discover:${profile.id}` ? "Discovering…" : discovery ? "Run again for this connection" : "Run discovery for this connection"}</button>
          {discovery?.categories && <div className={local.categoryGrid}>{discovery.categories.map((item) => <div className={local.categoryCard} key={item.id}><span className={`${local.categoryStatus} ${item.status === "OBSERVED" ? local.pass : item.status === "UNAVAILABLE" ? local.fail : local.pending}`}>{item.status}</span><strong>{item.count ?? "—"}</strong><b>{item.label}</b><small>{item.detail}</small></div>)}</div>}
        </article>;
      })}</div></details>}
    </section>
    <section className={`${styles.panel} ${local.catalogPanel}`}><header className={`${styles.panelHead} ${local.catalogHead}`}><div><span className={styles.eyebrow}>SAVED DISCOVERY INVENTORY</span><h2>Discovered assets</h2><p>Browse persisted discovery results first. Live connector diagnostics are separate below and never replace saved inventory.</p></div><div className={local.catalogToolbar}><div className={local.catalogSearch}><input className={local.search} aria-label="Search discovered assets" placeholder="Search table, DAG, model or file" value={query} onChange={(event) => setQuery(event.target.value)} /></div><label className={local.catalogFilter}>Environment<select aria-label="Filter by environment" value={filterEnvironment} onChange={(event) => setFilterEnvironment(event.target.value)}><option value="all">All environments</option>{availableEnvironments.map((value) => <option value={value} key={value}>{value}</option>)}</select></label><label className={local.catalogFilter}>Layer<select aria-label="Filter by pipeline layer" value={filterLayer} onChange={(event) => setFilterLayer(event.target.value)}><option value="all">All layers</option>{availableLayers.map((value) => <option value={value} key={value}>{value}</option>)}</select></label><label className={local.catalogFilter}>Connector<select aria-label="Filter by connector" value={filterConnection} onChange={(event) => setFilterConnection(event.target.value)}><option value="all">All connectors</option>{availableConnections.map(({ id, profile }) => <option value={id} key={id}>{profile?.name || id}</option>)}</select></label><label className={local.catalogFilter}>Asset type<select aria-label="Filter by asset type" value={filterType} onChange={(event) => setFilterType(event.target.value)}><option value="all">All asset types</option>{availableTypes.map((value) => <option value={value} key={value}>{value}</option>)}</select></label><button className={styles.quiet} onClick={() => { setQuery(""); setFilterEnvironment("all"); setFilterLayer("all"); setFilterConnection("all"); setFilterType("all"); }}>Reset</button><span className={local.catalogCount}>{assets.length} of {discoveredAssets.length} shown</span></div></header>{!Object.keys(discoveries).length ? <div className={local.empty}><strong>No discovery has been run</strong><p>Test a connection, then run discovery. Nothing is substituted when a connection is unavailable.</p></div> : <><AssetResultsTable assets={assets} connections={connections} selectedAssets={selectedAssets} onSelect={updateSelection} onOpenDetails={setCatalogAsset} /><details className={local.groupedCatalog}><summary>Browse grouped evidence catalog</summary><OrganizedAssetCatalog project={project} assets={assets} connections={connections} tests={tests} selectedAssets={selectedAssets} onSelect={updateSelection} /></details></>}</section>
  </div>;
  else content = <div className={styles.sectionStack}>
    <PostgresSourceTableDrilldown sourceTables={sourceTables} sourceStatus={sourceStatus} assets={discoveredAssets} connections={connections} tests={tests} selectedSourceTable={selectedSourceTable} selectedSourceTables={selectedSourceTables} sourceTableScopeId={bootstrap?.sourceTableScopeId} discoveryResultsByTable={discoveriesByTable} onAddSourceTable={addSourceTable} onAddAllSourceTables={addAllSourceTables} onSelectSourceTable={selectSourceTable} onRemoveSourceTable={removeSourceTable} onDiscoverAssets={() => void discoverSelectedAssets()} discoveryBusy={busy === "workflow-onboarding"} />
  </div>;

  const previousPhase = phase === "connections" ? "definition" : phase === "discovery" ? "connections" : phase === "onboarding" ? "discovery" : "overview";
  const nextPhase = phase === "overview" ? "definition" : phase === "definition" ? "connections" : phase === "connections" ? "discovery" : "onboarding";
  const workflowStatus = [
    project.name.trim() && project.owner.trim(),
    connectionReady,
    discoveryReady,
    mappingReady,
    qualityPlanReady,
    false,
  ];
  const laterPhaseState = [
    { title: "Lineage", detail: "Review evidence graph", href: "/project-design?view=map", available: discoveryReady, reason: "Requires every connection to pass testing and return discovery evidence.", next: "Confirm the evidence-backed mappings for the selected assets." },
    { title: "Define quality rules", detail: "Review deterministic checks", href: "/test-plan?view=contracts", available: mappingReady, reason: "Requires completed evidence-backed mapping for the selected assets.", next: "Generate or review the deterministic quality plan." },
    { title: "Review and run", detail: "Approve and execute", href: "/test-plan?view=execution", available: qualityPlanReady, reason: qualityPlanReady ? "No execution evidence exists yet. Approve and run the quality plan." : "Review the generated quality plan before execution.", next: "Approve the exact plan, then run it to create execution evidence." },
  ];
  const renderLifecycleItem = (item: typeof lifecyclePhases[number], index: number) => {
    const complete = Boolean(workflowStatus[index]);
    const later = laterPhaseState[index - 3];
    const available = index < 3 || Boolean(later?.available);
    const detail = complete ? "Complete" : available ? later?.next || item.detail : later?.reason || item.detail;
    const className = `${local.lifecycleItem} ${phase === item.id ? local.lifecycleItemActive : ""} ${complete ? local.lifecycleItemComplete : ""} ${!available ? local.lifecycleItemLocked : ""}`;
    const body = <><span className={local.lifecycleNumber}>{complete ? "✓" : index + 1}</span><span className={local.lifecycleCopy}><strong>{item.title}</strong><small>{detail}</small></span></>;
    if (index < 3) return <button className={className} key={item.id} onClick={() => setPhase(item.id as "definition" | "connections" | "discovery")}>{body}</button>;
    if (available && later) return <Link className={className} href={later.href} key={item.id}>{body}</Link>;
    return <div className={className} key={item.id} title={later?.reason}>{body}</div>;
  };
  const canDeleteProject = activeProjectId !== "new-project" && projects.length > 1;
  const deleteProjectTitle = activeProjectId === "new-project"
    ? "Save this project before deleting it"
    : projects.length <= 1
      ? "The only saved project cannot be deleted"
      : "Delete this project and its saved connections and discovery evidence";
  const projectOptions = activeProjectId === "new-project" ? [{ id: "new-project", name: "New unsaved project" }, ...projects] : projects.length ? projects : [{ id: activeProjectId, name: project.name || "New project" }];
  return <DraftShell active="register"><header className={`${styles.topbar} ${local.projectHeader}`}><div className={local.projectHeaderCopy}><span className={styles.eyebrow}>PROJECT MANAGEMENT</span><h1>Project management</h1><p>Manage the active project and complete its lifecycle from one focused workspace.</p><div className={local.projectMeta}><span>Project <strong>{project.name || "New data-quality project"}</strong></span><span>Environment <strong>{project.environment}</strong></span><span>Owner <strong>{project.owner || "Not assigned"}</strong></span><span>{lastSavedAt ? `Last saved ${new Date(lastSavedAt).toLocaleString()}` : "Not saved yet"}</span></div></div><div className={local.projectActions}><ProjectSelector projects={projectOptions} currentProjectId={activeProjectId} onChange={switchProject} /><button className={styles.secondary} onClick={startNewProject}>Start new project</button><button className={styles.secondary} onClick={() => { setSaveAsName(`${project.name || "New project"} copy`); setSaveAsOpen(true); }}>Save as new</button><button className={styles.primary} disabled={!projectDirty || !project.name.trim()} onClick={saveChanges}>Save changes</button><details className={local.projectMoreActions}><summary>More</summary><div><button className={styles.danger} disabled={!canDeleteProject || busy !== null} title={deleteProjectTitle} onClick={() => void deleteProject}>{busy === "delete-project" ? "Deleting…" : "Delete project"}</button></div></details></div></header>
    <Drawer open={saveAsOpen} title="Save as new project" eyebrow="PROJECT MANAGEMENT" onClose={() => setSaveAsOpen(false)} footer={<><button type="button" className={styles.quiet} onClick={() => setSaveAsOpen(false)}>Cancel</button><button type="button" className={styles.primary} onClick={saveAsNewProject}>Save copy</button></>}><p>Duplicate this definition under a new project name. Connections and evidence stay scoped to the original project.</p><label className={styles.field}>New project name<input aria-label="New project name" autoFocus value={saveAsName} onChange={(event) => setSaveAsName(event.target.value)} /></label></Drawer>
    {notice && <div className={notice.tone === "error" ? styles.dangerStrip : styles.successStrip} role={notice.tone === "error" ? "alert" : "status"}>{notice.text}</div>}<div className={local.managementFrame}><aside className={local.managementNav}><button className={`${local.lifecycleItem} ${phase === "overview" ? local.lifecycleItemActive : ""}`} onClick={() => setPhase("overview")}><span className={local.lifecycleNumber}>⌂</span><span className={local.lifecycleCopy}><strong>Overview</strong><small>Project health and next action</small></span></button><div className={local.navSectionLabel}>PROJECT MANAGEMENT</div><button className={`${local.lifecycleItem} ${phase === "onboarding" ? local.lifecycleItemActive : ""}`} onClick={() => setPhase("onboarding")}><span className={local.lifecycleNumber}>↳</span><span className={local.lifecycleCopy}><strong>Data onboarding</strong><small>Choose one source table</small></span></button><div className={local.navSectionLabel}>PROJECT LIFECYCLE</div>{lifecyclePhases.map(renderLifecycleItem)}</aside><main className={local.managementMain}><div className={`${styles.designerGrid} ${local.managementGrid}`}><div>{content}</div></div>
    <footer className={`${styles.footerBar} ${local.projectFooter}`}><span>{projectDirty ? "Unsaved changes — save before switching projects." : `Project saved ${lastSavedAt ? new Date(lastSavedAt).toLocaleString() : "not yet recorded"}.`}</span><div>{phase === "overview" ? <button className={styles.primary} onClick={() => setPhase("definition")}>Start with project definition →</button> : <><button className={styles.quiet} disabled={phase === "definition"} onClick={() => setPhase(previousPhase)}>← Back</button>{phase === "definition" || phase === "connections" ? <button className={styles.primary} onClick={() => setPhase(nextPhase)}>Continue →</button> : phase === "discovery" && mappingReady ? <Link className={`${styles.primary} ${styles.linkButton}`} href="/project-design?view=roles">Continue to asset roles →</Link> : <span className={local.footerHint}>Complete the required evidence above to continue.</span>}</>}</div></footer></main></div>{editing && <ConnectionEditor profile={editing} onCancel={() => setEditing(null)} onSave={(profile) => void saveProfile(profile)} />}{phase === "discovery" && <AssetInspector asset={catalogAsset} profile={catalogAsset ? connections.find((item) => item.id === catalogAsset.connectionId) : undefined} test={catalogAsset ? tests[catalogAsset.connectionId] : undefined} selected={catalogAsset ? selectedAssets.includes(catalogAsset.id) : false} onSelect={(selected) => { if (catalogAsset) updateSelection(catalogAsset.id, selected); }} onClose={() => setCatalogAsset(null)} />}
  </DraftShell>;
}

export default function ProjectOnboardingPageWithSuspense() {
  return <Suspense fallback={<div aria-live="polite">Loading project management…</div>}><ProjectOnboardingPage /></Suspense>;
}
