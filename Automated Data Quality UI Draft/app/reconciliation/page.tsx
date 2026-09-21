"use client";

import { useEffect, useState, type FormEvent } from "react";
import DraftShell from "../DraftShell";
import { scopedApiUrl } from "../../lib/client-workspace";
import styles from "./reconciliation.module.css";
import { PageHeader, StatusBadge } from "../components/ui";

type Item = Record<string, unknown>;
type History = { items?: Item[]; count?: number };
type CatalogItem = { database?: string; schema: string; table: string; label: string; columns: string[] };
type ConnectionDefaults = { databases?: { source?: string; target?: string }; schemas?: { source?: string; target?: string }; connectionStatus?: { source?: string; target?: string }; catalogs?: { source?: CatalogItem[]; target?: CatalogItem[] } };
type HistoryRow = { id: string; type: string; source: string; target: string; field: string; status: string; observed: string; timestamp: unknown; details: Item };

function text(value: unknown, fallback = "—"): string { return value === null || value === undefined || value === "" ? fallback : String(value); }
function number(value: unknown): number { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : 0; }
function countText(value: unknown): string { return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "Unavailable"; }
function date(value: unknown): string { if (!value) return "Not available"; const parsed = new Date(String(value)); return Number.isNaN(parsed.getTime()) ? "Not available" : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); }
function assetLabel(value: unknown): string {
  if (!value || typeof value !== "object") return text(value);
  const item = value as Item;
  const qualifiedName = item.qualified_name;
  if (qualifiedName) return text(qualifiedName);
  const hasDatabasePath = Boolean(item.database && item.schema && item.table);
  if (hasDatabasePath) return `${item.database}.${item.schema}.${item.table}`;
  return text(item.name);
}

function pairFromReport(report: Item): { sourceSchema: string; sourceTable: string; targetSchema: string; targetTable: string; keyColumn: string } | null {
  const relationships = Array.isArray(report.relationship_classifications) ? report.relationship_classifications as Item[] : [];
  for (const relation of relationships) {
    const source = text(relation.source_name, "");
    const target = text(relation.target_name, "");
    if (!source || !target || !source.toLowerCase().startsWith("postgres.")) continue;
    const sourceParts = source.split(".").filter(Boolean);
    const targetParts = target.split(".").filter(Boolean);
    if (sourceParts.length < 3 || targetParts.length < 2) continue;
    const keys = Array.isArray(relation.key_columns) ? relation.key_columns : [relation.key_column];
    return { sourceSchema: sourceParts.at(-2) ?? "public", sourceTable: sourceParts.at(-1) ?? "", targetSchema: targetParts.at(-2) ?? "RAW", targetTable: targetParts.at(-1) ?? "", keyColumn: text(keys[0], "") };
  }
  return null;
}

export default function ReconciliationPage() {
  const [history, setHistory] = useState<Item[]>([]);
  const [qualityHistory, setQualityHistory] = useState<Item[]>([]);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyType, setHistoryType] = useState("ALL");
  const [historyStatus, setHistoryStatus] = useState("ALL");
  const [suggested, setSuggested] = useState(pairFromReport({}));
  const [defaults, setDefaults] = useState<ConnectionDefaults>({});
  const [catalogs, setCatalogs] = useState<{ source: CatalogItem[]; target: CatalogItem[] }>({ source: [], target: [] });
  const [loadingDefaults, setLoadingDefaults] = useState(true);
  const [form, setForm] = useState({ sourceSchema: "public", sourceDatabase: "", sourceTable: "", targetSchema: "RAW", targetDatabase: "", targetTable: "", checkType: "ROW_COUNT", checkSide: "source" as "source" | "target", checkColumn: "", keyColumn: "", sourceKeyColumn: "", targetKeyColumn: "", maxKeys: "50000", pipelineRunId: "" });
  const [result, setResult] = useState<Item | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [resultNotice, setResultNotice] = useState<string | null>(null);

  const load = () => Promise.all([
    fetch(scopedApiUrl("/api/reconciliation"), { cache: "no-store" }).then(async (response) => { const value = await response.json() as { history?: History; qualityHistory?: { items?: Item[] }; error?: string } & ConnectionDefaults; if (!response.ok) throw new Error(value.error || "Unable to load reconciliation history"); const items = value.history?.items ?? []; const latest = items[0]; const latestSource = latest?.source && typeof latest.source === "object" ? latest.source as Item : {}; const latestTarget = latest?.target && typeof latest.target === "object" ? latest.target as Item : {}; const latestResult = latest?.result && typeof latest.result === "object" ? latest.result as Item : {}; const sourceKeys = Array.isArray(latestResult.source_key_columns) ? latestResult.source_key_columns : []; const targetKeys = Array.isArray(latestResult.target_key_columns) ? latestResult.target_key_columns : []; const sourceCatalog = value.catalogs?.source ?? []; const targetCatalog = value.catalogs?.target ?? []; setHistory(items); setQualityHistory(value.qualityHistory?.items ?? []); setDefaults({ databases: value.databases, schemas: value.schemas, connectionStatus: value.connectionStatus }); setCatalogs({ source: sourceCatalog, target: targetCatalog }); setForm((current) => ({ ...current, sourceDatabase: value.databases?.source || current.sourceDatabase, targetDatabase: value.databases?.target || current.targetDatabase, sourceSchema: value.schemas?.source || current.sourceSchema, targetSchema: value.schemas?.target || current.targetSchema, sourceTable: current.sourceTable || text(latestSource.table, sourceCatalog[0]?.table ?? ""), targetTable: current.targetTable || text(latestTarget.table, targetCatalog[0]?.table ?? ""), keyColumn: current.keyColumn || text(latest?.key_column, ""), sourceKeyColumn: current.sourceKeyColumn || text(sourceKeys[0], text(latest?.key_column, "")), targetKeyColumn: current.targetKeyColumn || text(targetKeys[0], text(latest?.key_column, "")) })); }).finally(() => setLoadingDefaults(false)),
    fetch(scopedApiUrl("/api/project-analysis"), { cache: "no-store" }).then(async (response) => { if (!response.ok) return; const value = await response.json() as { report?: Item | null }; const pair = pairFromReport(value.report ?? {}); if (pair) { setSuggested(pair); setForm((current) => ({ ...current, ...pair })); } }),
  ]).catch((reason: Error) => setError(reason.message));

  useEffect(() => { void load().then(() => setLastRefreshed(new Date())); }, []);
  const refreshHistory = () => { setRefreshing(true); setError(null); setResultNotice(null); void load().finally(() => { setRefreshing(false); setLastRefreshed(new Date()); }); };
  const baseline = !form.pipelineRunId.trim();
  const contextLabel = baseline ? "BASELINE / PRE-EXECUTION" : "POST-EXECUTION EVIDENCE";
  const contextClass = baseline ? styles.contextBaseline : styles.contextPost;
  const sourceCatalogItem = catalogs.source.find((item) => item.schema === form.sourceSchema && item.table === form.sourceTable);
  const targetCatalogItem = catalogs.target.find((item) => item.schema === form.targetSchema && item.table === form.targetTable);
  const sourceConnectionStatus = text(defaults.connectionStatus?.source, "UNAVAILABLE");
  const targetConnectionStatus = text(defaults.connectionStatus?.target, "UNAVAILABLE");
  const sourceStatusClass = ["CONNECTED", "CACHED DISCOVERY"].includes(sourceConnectionStatus.toUpperCase()) ? styles.configured : styles.unavailable;
  const targetStatusClass = ["CONNECTED", "CACHED DISCOVERY"].includes(targetConnectionStatus.toUpperCase()) ? styles.configured : styles.unavailable;
  const checkColumns = form.checkSide === "target" ? targetCatalogItem?.columns ?? [] : sourceCatalogItem?.columns ?? [];
  const selectedSourceLabel = sourceCatalogItem?.label ?? [form.sourceDatabase, form.sourceSchema, form.sourceTable].filter(Boolean).join(".");
  const selectedTargetLabel = targetCatalogItem?.label ?? [form.targetDatabase, form.targetSchema, form.targetTable].filter(Boolean).join(".");
  const selectTable = (side: "source" | "target", value: string) => { const item = (side === "source" ? catalogs.source : catalogs.target).find((candidate) => candidate.label === value); if (!item) return; setForm((current) => ({ ...current, [`${side}Schema`]: item.schema, [`${side}Table`]: item.table, ...(current.checkSide === side ? { checkColumn: "" } : {}), ...(side === "source" ? { sourceKeyColumn: "" } : { targetKeyColumn: "" }) })); };

  const execute = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null); setResult(null); setResultNotice(null);
    try {
      const response = await fetch(scopedApiUrl("/api/reconciliation"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...form, keyColumn: form.checkType === "MINUS" ? form.keyColumn : "" }) });
      const value = await response.json() as { result?: Item; error?: string };
      if (!response.ok) throw new Error(value.error || "Reconciliation failed");
      setResult(value.result ?? null); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Reconciliation failed"); }
    finally { setBusy(false); }
  };

  const resultDetails = result ? (result.result && typeof result.result === "object" ? result.result as Item : result) : null;
  const source = resultDetails?.source && typeof resultDetails.source === "object" ? resultDetails.source as Item : {};
  const target = resultDetails?.target && typeof resultDetails.target === "object" ? resultDetails.target as Item : {};
  const keyComparison = resultDetails?.key_comparison && typeof resultDetails.key_comparison === "object" ? resultDetails.key_comparison as Item : {};
  const currentRun = resultDetails?.execution_context && typeof resultDetails.execution_context === "object" ? resultDetails.execution_context as Item : {};
  const comparisonUnavailable = resultDetails && resultDetails.metric !== "live_table_reconciliation";
  const historyRows: HistoryRow[] = [...history.map((item, index) => { const value = item.result && typeof item.result === "object" ? item.result as Item : {}; const sourceValue = item.source && typeof item.source === "object" ? item.source as Item : {}; const targetValue = item.target && typeof item.target === "object" ? item.target as Item : {}; const sourceKeys = Array.isArray(value.source_key_columns) ? value.source_key_columns : []; const targetKeys = Array.isArray(value.target_key_columns) ? value.target_key_columns : []; return { id: text(item.result_id, `reconciliation-${index}`), type: item.key_column || sourceKeys.length ? "MINUS" : "ROW COUNT", source: assetLabel(item.source), target: assetLabel(item.target), field: sourceKeys.length || targetKeys.length ? `${sourceKeys.map(String).join(", ")} → ${targetKeys.map(String).join(", ")}` : "—", status: text(item.status, "UNKNOWN"), observed: `${number(sourceValue.row_count)} → ${number(targetValue.row_count)} (${number(item.row_count_difference)} diff)`, timestamp: item.timestamp, details: { ...value, source: sourceValue, target: targetValue } }; }), ...qualityHistory.map((item, index) => { const details = item.details && typeof item.details === "object" ? item.details as Item : {}; const checkType = text(item.check_type, "QUALITY").toUpperCase(); return { id: text(item.result_id, `quality-${index}`), type: checkType === "COMPLETENESS" ? "NULL CHECK" : checkType === "UNIQUENESS" ? "DUPLICATE CHECK" : checkType.replaceAll("_", " "), source: `${text(item.system, "database")} · ${text(item.asset)}`, target: "—", field: Array.isArray(details.columns) ? details.columns.map(String).join(", ") : text(details.column, "—"), status: text(item.status, "UNKNOWN"), observed: typeof item.observed_value === "object" ? JSON.stringify(item.observed_value) : text(item.observed_value), timestamp: item.timestamp, details: { ...item, details } }; })].sort((left, right) => new Date(String(right.timestamp)).getTime() - new Date(String(left.timestamp)).getTime());
  const filteredHistoryRows = historyRows.filter((item) => {
    const query = historyQuery.trim().toLowerCase();
    const matchesQuery = !query || [item.type, item.source, item.target, item.field, item.status, item.observed].some((value) => value.toLowerCase().includes(query));
    const matchesType = historyType === "ALL" || item.type === historyType;
    const matchesStatus = historyStatus === "ALL" || item.status.toUpperCase() === historyStatus;
    return matchesQuery && matchesType && matchesStatus;
  });
  const selectedHistory = historyRows.find((item) => item.id === selectedHistoryId) ?? null;
  const clearDisplayedResult = () => { setResult(null); setSelectedHistoryId(null); setHistory([]); setQualityHistory([]); setResultNotice("Displayed results cleared from this view. Click Refresh history to restore the saved verification records."); };

  return <DraftShell active="reconciliation">
    <PageHeader eyebrow="AUTOMATED DATA QUALITY / VERIFY" title="Source-to-target reconciliation" description="Choose the two tables and the check you want to run. Connector schemas stay behind the scenes." status={lastRefreshed ? <span className={styles.refreshState}>Last refreshed {lastRefreshed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}</span> : <StatusBadge value="NOT_CHECKED" label="Not refreshed" />} actions={<button className={styles.secondary} onClick={refreshHistory} disabled={refreshing}>{refreshing ? "Refreshing…" : "Refresh history"}</button>} />
    <div className={styles.layout}><main>
      <section className={styles.panel}><header className={styles.panelHeader}><div><h2>Run a table comparison</h2><p>Current live adapter scope: PostgreSQL source → Snowflake target. This does not change either system.</p></div><span className={styles.badge}>READ-ONLY</span></header>
        <div className={`${styles.contextBanner} ${contextClass}`}><strong>{contextLabel}</strong><span>{baseline ? "No incident will be created from this baseline comparison." : "The supplied pipeline run ID links this result to post-execution evidence."}</span></div>
        <div className={styles.scopeSummary}><div><span>Source</span><strong>{selectedSourceLabel || "Choose a source table"}</strong></div><div><span>Target</span><strong>{selectedTargetLabel || "Choose a target table"}</strong></div><div><span>Check</span><strong>{form.checkType.replaceAll("_", " ")}</strong></div><div><span>Run association</span><strong>{form.pipelineRunId.trim() || "None · baseline"}</strong></div></div>
        <form onSubmit={execute}><div className={styles.formGrid}>
          <label className={styles.field}>Source database <span className={loadingDefaults ? styles.configured : sourceStatusClass}>● {loadingDefaults ? "Loading" : sourceConnectionStatus}</span><input value={form.sourceDatabase || (loadingDefaults ? "Loading…" : text(defaults.databases?.source, "Unavailable"))} readOnly aria-readonly="true" placeholder="hospitality_oltp" required /></label>
          <label className={styles.field}>Source table<select value={sourceCatalogItem?.label ?? ""} onChange={(event) => selectTable("source", event.target.value)} required><option value="">Choose source database.schema.table</option>{catalogs.source.map((item) => <option key={item.label} value={item.label}>{item.label}</option>)}</select></label>
          <label className={styles.field}>Target database <span className={loadingDefaults ? styles.configured : targetStatusClass}>● {loadingDefaults ? "Loading" : targetConnectionStatus}</span><input value={form.targetDatabase || (loadingDefaults ? "Loading…" : text(defaults.databases?.target, "Unavailable"))} readOnly aria-readonly="true" placeholder="HOSPITALITY_RELIABILITY_LAB" required /></label>
          <label className={styles.field}>Target table<select value={targetCatalogItem?.label ?? ""} onChange={(event) => selectTable("target", event.target.value)} required><option value="">Choose target database.schema.table</option>{catalogs.target.map((item) => <option key={item.label} value={item.label}>{item.label}</option>)}</select></label>
          <label className={styles.field}>Check type<select value={form.checkType} onChange={(event) => setForm({ ...form, checkType: event.target.value, keyColumn: event.target.value === "MINUS" ? form.keyColumn : "", checkColumn: ["NULL", "DUPLICATE"].includes(event.target.value) ? form.checkColumn : "" })}><option value="ROW_COUNT">Row count</option><option value="MINUS">Minus / key difference</option><option value="NULL">Null check</option><option value="DUPLICATE">Duplicate check</option></select></label>
          {form.checkType === "MINUS" && <><label className={styles.field}>Source key column <span className={styles.optional}>from {form.sourceSchema}.{form.sourceTable || "source table"}</span><select value={form.sourceKeyColumn} onChange={(event) => setForm({ ...form, sourceKeyColumn: event.target.value, keyColumn: event.target.value })} required><option value="">Choose source key column</option>{sourceCatalogItem?.columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></label><label className={styles.field}>Target key column <span className={styles.optional}>from {form.targetSchema}.{form.targetTable || "target table"}</span><select value={form.targetKeyColumn} onChange={(event) => setForm({ ...form, targetKeyColumn: event.target.value })} required><option value="">Choose target key column</option>{targetCatalogItem?.columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></label></>}
          {["NULL", "DUPLICATE"].includes(form.checkType) && <><label className={styles.field}>Check side<select value={form.checkSide} onChange={(event) => setForm({ ...form, checkSide: event.target.value as "source" | "target", checkColumn: "" })}><option value="source">Source table</option><option value="target">Target table</option></select></label><label className={styles.field}>{form.checkType === "NULL" ? "Column to check for nulls" : "Column to check for duplicates"}<select value={form.checkColumn} onChange={(event) => setForm({ ...form, checkColumn: event.target.value })} required><option value="">Choose a column</option>{checkColumns.map((column) => <option key={column} value={column}>{column}</option>)}</select></label></>}
        </div><details className={styles.advancedOptions}><summary>Advanced options <span>Scan limits and run association</span></summary><div className={styles.advancedGrid}><label className={styles.field}>Max keys scanned<input type="number" min="100" max="50000" value={form.maxKeys} onChange={(event) => setForm({ ...form, maxKeys: event.target.value })} /></label><label className={styles.field}>Pipeline run ID <span className={styles.optional}>leave blank before a pipeline run</span><input value={form.pipelineRunId} onChange={(event) => setForm({ ...form, pipelineRunId: event.target.value })} placeholder="e.g. airflow run or quality run identifier" /></label></div><p className={styles.advancedHint}>Effective scope remains visible above. A run ID links the comparison to post-execution evidence; it does not start a pipeline.</p></details><div className={styles.actions}><button className={styles.primary} disabled={busy}>{busy ? "Comparing…" : "Run read-only comparison"}</button><span>Counts, key differences, null keys, and duplicate groups are retained as evidence.</span></div></form>
      </section>
      {resultDetails && <section className={styles.panel}><header className={styles.panelHeader}><div><h2>Comparison result</h2><p>{assetLabel(resultDetails.source)} → {assetLabel(resultDetails.target)} · {date(resultDetails.timestamp ?? resultDetails.created_at)}</p></div><div className={styles.resultHeaderActions}><span className={`${styles.badge} ${text(resultDetails.status).toUpperCase() === "PASS" ? styles.good : styles.bad}`}>{text(resultDetails.status, "UNKNOWN")}</span><button className={styles.detailButton} onClick={clearDisplayedResult}>Clear displayed result</button></div></header>
        {comparisonUnavailable && <div className={styles.warningNotice}><strong>Comparison not completed</strong><span>{text(resultDetails.reason, "The live adapter did not return row counts.")}</span></div>}<div className={styles.metricGrid}><div><span>Source rows</span><strong>{countText(source.row_count)}</strong></div><div><span>Target rows</span><strong>{countText(target.row_count)}</strong></div><div><span>Difference</span><strong>{countText(resultDetails.row_count_difference)}</strong></div><div><span>Incident eligible</span><strong>{text(currentRun.incident_eligible, "false")}</strong></div></div>
        <div className={styles.diffGrid}><article><span>Source − target</span><strong>{number(keyComparison.missing_in_snowflake_count)}</strong><small>source keys missing in target</small></article><article><span>Target − source</span><strong>{number(keyComparison.extra_in_snowflake_count)}</strong><small>target keys not found in source</small></article><article><span>Null keys</span><strong>{number(keyComparison.source_null_key_count)} / {number(keyComparison.target_null_key_count)}</strong><small>source / target</small></article><article><span>Duplicate groups</span><strong>{number(keyComparison.source_duplicate_key_groups)} / {number(keyComparison.target_duplicate_key_groups)}</strong><small>source / target</small></article></div>
        <div className={styles.evidenceNote}><strong>Persisted evidence</strong><span>Run {text(resultDetails.run_id)} · Result {text(resultDetails.result_id)} · {currentRun.incident_eligible ? "linked to post-execution context" : "baseline only; not an incident"}</span>{Array.isArray(resultDetails.source_key_columns) && <span>Keys compared: {resultDetails.source_key_columns.map(String).join(", ")} → {Array.isArray(resultDetails.target_key_columns) ? resultDetails.target_key_columns.map(String).join(", ") : "—"}</span>}</div>
      </section>}
    </main><aside className={styles.side}><section className={styles.panel}><h3>Suggested pair</h3><p>Derived from the latest accepted project analysis when available. Review before running.</p>{suggested ? <div className={styles.suggestion}><strong>{suggested.sourceSchema}.{suggested.sourceTable}</strong><span>→</span><strong>{suggested.targetSchema}.{suggested.targetTable}</strong><small>Key: {suggested.keyColumn || "not inferred"}</small></div> : <div className={styles.empty}>No source-to-target pair was inferred from the latest analysis.</div>}</section><section className={styles.panel}><h3>What this checks</h3><ul><li>Row-count equality</li><li>Source-minus-target keys</li><li>Target-minus-source keys</li><li>Null key counts</li><li>Duplicate key groups</li></ul></section></aside></div>
    <section className={`${styles.panel} ${styles.history}`}><header className={styles.panelHeader}><div><h2>Verification history</h2><p>Reconciliation, Null, and Duplicate results are shown together with their exact scope.</p></div><div className={styles.historyHeaderActions}><span className={styles.badge}>{filteredHistoryRows.length} OF {historyRows.length} RESULTS</span><button className={styles.detailButton} onClick={clearDisplayedResult}>Clear displayed result</button></div></header><div className={styles.historyFilters}><label>Search history<input value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="Table, check, key or result" /></label><label>Check type<select value={historyType} onChange={(event) => setHistoryType(event.target.value)}><option value="ALL">All checks</option><option value="ROW COUNT">Row count</option><option value="MINUS">Minus</option><option value="NULL CHECK">Null check</option><option value="DUPLICATE CHECK">Duplicate check</option></select></label><label>Status<select value={historyStatus} onChange={(event) => setHistoryStatus(event.target.value)}><option value="ALL">All statuses</option><option value="PASS">Pass</option><option value="FAIL">Fail</option><option value="ERROR">Error</option></select></label></div>{filteredHistoryRows.length ? <div className={styles.historyTableWrap}><table className={styles.historyTable}><thead><tr><th>Check</th><th>Source</th><th>Target / scope</th><th>Key or column</th><th>Status</th><th>Observed</th><th>When</th><th></th></tr></thead><tbody>{filteredHistoryRows.slice(0, 100).map((item) => <tr key={item.id} className={selectedHistoryId === item.id ? styles.selectedHistoryRow : ""}><td><strong>{item.type}</strong></td><td>{item.source}</td><td>{item.target}</td><td>{item.field}</td><td><span className={`${styles.badge} ${item.status.toUpperCase() === "PASS" ? styles.good : styles.bad}`}>{item.status}</span></td><td>{item.observed}</td><td>{date(item.timestamp)}</td><td><button className={styles.detailButton} onClick={() => setSelectedHistoryId(item.id)}>View details</button></td></tr>)}</tbody></table></div> : <div className={styles.empty}>{historyRows.length ? "No results match these filters." : "No results yet."}</div>}{selectedHistory && <div className={styles.historyDetail} role="dialog" aria-label="Verification result details"><div><strong>{selectedHistory.type}</strong><span>{selectedHistory.source} → {selectedHistory.target}</span><small>{date(selectedHistory.timestamp)} · {selectedHistory.status}</small></div><div className={styles.historyDetailActions}><button className={styles.detailButton} onClick={clearDisplayedResult}>Clear displayed result</button><button className={styles.detailButton} onClick={() => setSelectedHistoryId(null)}>Close details</button></div><div className={styles.detailSummary}><span>Key or column <strong>{selectedHistory.field}</strong></span><span>Observed <strong>{selectedHistory.observed}</strong></span></div><pre>{JSON.stringify(selectedHistory.details, null, 2)}</pre></div>}</section>
    {resultNotice && <div className={styles.successNotice}>{resultNotice}</div>}{error && <div className={styles.error}>{error}</div>}
  </DraftShell>;
}
