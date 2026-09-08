"use client";

import type { CSSProperties, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { API, getJson, postJson } from "../lib/api";
import InvestigationConsole from "./InvestigationConsole";
import SessionConsole from "./SessionConsole";
import TraceConsole from "./TraceConsole";

type Status = "PASS" | "FAIL" | "WARN" | "SKIP" | "PARTIAL" | string;
type RecordValue = Record<string, unknown>;

type Overview = {
  mode: string;
  project: string;
  generated_at: string;
  health_score: number;
  health_status: Status;
  counts: {
    sources: number;
    oracle_tables: number;
    postgres_tables: number;
    file_feeds: number;
    airflow_dags: number;
    dbt_models: number;
    dbt_tests: number;
    dbt_snapshots: number;
    tools: number;
  };
  dbt_coverage: DbtCoverage;
  quality: QualitySummary;
  migration: { blockers: number; engine: string };
  live_integrations: Record<string, string>;
  findings: Finding[];
  health_components: Record<string, { status: Status; detail: string }>;
};

type Finding = { severity: string; source: string; title: string; detail: string };
type Inventory = {
  mode: string;
  dbt: RecordValue & { models?: number; tests?: number; snapshots?: number };
  airflow: RecordValue & { dag_count?: number };
  snowflake: RecordValue & { objects?: Record<string, number>; live_status?: string };
  sources: {
    oracle_tables: number;
    postgres_tables: number;
    file_feeds: number;
  };
  shiftforge: RecordValue & { found?: boolean };
  local_data_harness: RecordValue & { found?: boolean };
};
type AssetNode = { node_id: string; kind: string; name: string; properties: RecordValue };
type TraversalNode = AssetNode & { depth?: number };
type AssetsResponse = {
  total: number;
  returned: number;
  node_types: Record<string, number>;
  edge_types: Record<string, number>;
  items: AssetNode[];
};
type LineageResponse = { asset: AssetNode; upstream: TraversalNode[]; downstream: TraversalNode[] };
type ImpactResponse = {
  changed_asset: AssetNode;
  downstream: TraversalNode[];
  affected_marts: TraversalNode[];
  affected_tests: TraversalNode[];
  severity: string;
};
type DbtSummary = { resource_counts: Record<string, number>; total_nodes: number; artifacts: Record<string, boolean> };
type DbtCoverage = {
  models: number;
  tested_models: string[];
  untested_models: string[];
  tested_count: number;
  untested_count: number;
  coverage_pct: number;
};
type DbtDocs = {
  missing_model_descriptions: string[];
  missing_column_descriptions: { model: string; column: string }[];
  model_gap_count: number;
  column_gap_count: number;
};
type AirflowDag = {
  dag_id: string;
  file: string;
  schedule: string | null;
  catchup: boolean | null;
  retries: number | null;
  tasks: string[];
  operators: string[];
  task_groups: string[];
  connections: string[];
  source: string | null;
  entities: string[];
  writes: string[];
  dbt_commands: string[];
};
type AirflowInventory = { dag_count: number; parse_errors: RecordValue[]; connections_used: string[]; dags: string[]; details: AirflowDag[] };
type QualityItem = {
  result_id: string;
  check_id: string;
  run_id: string;
  system: string;
  layer: string;
  asset: string;
  check_type: string;
  severity: string;
  status: Status;
  observed_value: unknown;
  expected_value: unknown;
  timestamp: string;
};
type ReconciliationHistory = { result_id: string; run_id: string; metric: string; status: Status; timestamp: string; result: RecordValue };
type QualitySummary = {
  run_count: number;
  result_count: number;
  reconciliation_count: number;
  status_counts: Record<string, number>;
  reconciliation_status_counts: Record<string, number>;
  recent_results: QualityItem[];
  recent_reconciliations: ReconciliationHistory[];
};
type SqlReview = {
  parseable: boolean;
  dialect: string;
  statement_type?: string;
  statement_count?: number;
  tables: string[];
  status: Status;
  findings: { rule_id: string; severity: string; message: string; line?: number | null; column?: number | null; evidence?: string; recommendation?: string }[];
};
type SqlLineage = {
  parseable: boolean;
  status: Status;
  tables?: string[];
  mappings?: { target_column: string; expression: string; resolved: boolean; sources: { table: string; column: string }[] }[];
  unresolved?: { column: string; reason: string }[];
  error?: string;
};
type ReconcileResult = {
  metric: string;
  source_value: number;
  target_value: number;
  difference: number;
  difference_pct: number;
  tolerance: { absolute: number; percentage: number };
  status: Status;
};
type MigrationInventory = {
  source_dialect: string;
  target_dialect: string;
  project: string;
  models: number;
  model_paths?: string[];
  sources?: number;
  tests?: number;
  snapshots?: number;
  incremental_models?: number;
};
type MigrationFindings = { count: number; findings: RecordValue[] };
type MigrationBlockers = { count: number; blockers: RecordValue[] };
type WarehouseStatus = {
  mode: string;
  adapters: {
    name: string;
    adapter_available: boolean;
    driver_installed: boolean;
    credentials_configured: boolean;
    live_connectivity: string;
    simulation_available: boolean;
    status: Status;
  }[];
};
type AgentAnswer = {
  question: string;
  result: unknown;
  evidence: { tools_used: string[]; data_sources: string[]; timestamp: string; mode: string };
};
type DataDiffDemo = {
  mode: string;
  status: Status;
  source: string;
  target: string;
  schema: { status: Status; missing_columns: string[]; extra_columns: string[]; type_mismatches: RecordValue[] };
  row_count: { status: Status; source_count: number; target_count: number; difference: number };
  rows: { status: Status; counts: { matches: number; missing: number; extra: number; changed: number }; changed_rows: RecordValue[] };
  hash: { status: Status; changed_keys: unknown[]; missing_keys: unknown[]; extra_keys: unknown[] };
  aggregates: { column: string; aggregate: string; source_value: number; target_value: number; difference: number; status: Status }[];
};
type AirflowOperations = {
  retry: { status: Status; configured_count: number; missing_or_zero_count: number; missing_or_zero: string[] };
  schedule: { status: Status; unscheduled: string[]; catchup_enabled: string[]; schedule_counts: Record<string, number> };
  backfill: { status: Status; risk_count: number; risks: RecordValue[]; recommendation: string };
  connections: { connection_count: number; connections: { connection_id: string; dag_count: number; dags: string[] }[] };
  health: { score: number; status: Status; components: Record<string, RecordValue>; live_runtime: string };
  runtime: { status: Status; static_inventory_ready: boolean; parse_error_count: number; live_api: string; logs: string };
};
type AirflowFailureLab = {
  mode: string;
  event: { dag_id: string; task_id: string; state: string; error: string };
  diagnosis: { cause: string; confidence: number; evidence: string[]; recommended_action: string; status: string };
};
type SqlProposal = {
  status: string;
  finding_count: number;
  proposals: { rule_id: string; problem: string; proposal: string; automatic_edit: boolean }[];
  applied: boolean;
  requires_builder_approval: boolean;
};

const NAV = [
  "Overview", "Investigations", "Agent", "Assets", "Lineage", "SQL Intelligence", "dbt", "Airflow",
  "Data Quality", "Reconciliation", "Warehouses", "Connections", "Metadata", "Data Diff",
  "Migration", "Cost / FinOps", "Governance / PII", "PR Reviews", "Skills", "Training",
  "Providers", "MCP", "Jobs", "Traces", "Sessions", "Runs / Evidence", "Settings / Doctor",
];

const DEFAULT_SQL = `WITH orders AS (
  SELECT * FROM raw.orders
)
SELECT *
FROM orders o
CROSS JOIN raw.customers c
WHERE DATE(o.created_at) = CURRENT_DATE()`;

function badgeClass(status: Status) {
  const key = String(status).toUpperCase();
  if (key === "PASS" || key === "HEALTHY" || key === "AVAILABLE") return "status status-pass";
  if (key === "FAIL" || key === "CRITICAL" || key === "ERROR") return "status status-fail";
  if (key === "SKIP") return "status status-skip";
  return "status status-warn";
}

function StatusBadge({ status }: { status: Status }) {
  return <span className={badgeClass(status)}>{String(status)}</span>;
}

function Panel({ title, eyebrow, actions, children, className = "" }: { title: string; eyebrow?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h2>{title}</h2></div>
        {actions && <div className="panel-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

function Metric({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return <article className="metric"><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</article>;
}

function Loading({ text = "Loading evidence…" }: { text?: string }) {
  return <div className="loading"><span className="spinner" />{text}</div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

function compact(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function OperatorConsole() {
  const [active, setActive] = useState("Overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [assets, setAssets] = useState<AssetsResponse | null>(null);
  const [dbtSummary, setDbtSummary] = useState<DbtSummary | null>(null);
  const [dbtCoverage, setDbtCoverage] = useState<DbtCoverage | null>(null);
  const [dbtDocs, setDbtDocs] = useState<DbtDocs | null>(null);
  const [airflow, setAirflow] = useState<AirflowInventory | null>(null);
  const [quality, setQuality] = useState<QualitySummary | null>(null);
  const [migration, setMigration] = useState<MigrationInventory | null>(null);
  const [migrationFindings, setMigrationFindings] = useState<MigrationFindings | null>(null);
  const [migrationBlockers, setMigrationBlockers] = useState<MigrationBlockers | null>(null);
  const [warehouses, setWarehouses] = useState<WarehouseStatus | null>(null);
  const [dataDiff, setDataDiff] = useState<DataDiffDemo | null>(null);
  const [airflowOperations, setAirflowOperations] = useState<AirflowOperations | null>(null);
  const [airflowFailureLab, setAirflowFailureLab] = useState<AirflowFailureLab | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [assetQuery, setAssetQuery] = useState("");
  const [lineageNode, setLineageNode] = useState("fact_reservation");
  const [lineage, setLineage] = useState<LineageResponse | null>(null);
  const [impact, setImpact] = useState<ImpactResponse | null>(null);
  const [lineageBusy, setLineageBusy] = useState(false);

  const [sql, setSql] = useState(DEFAULT_SQL);
  const [dialect, setDialect] = useState("snowflake");
  const [sqlReview, setSqlReview] = useState<SqlReview | null>(null);
  const [sqlLineage, setSqlLineage] = useState<SqlLineage | null>(null);
  const [sqlProposal, setSqlProposal] = useState<SqlProposal | null>(null);
  const [sqlBusy, setSqlBusy] = useState(false);

  const [sourceCount, setSourceCount] = useState(10000);
  const [targetCount, setTargetCount] = useState(9998);
  const [reconcile, setReconcile] = useState<ReconcileResult | null>(null);

  const [agentQuestion, setAgentQuestion] = useState("What depends on stg_oracle_reservation?");
  const [agentAnswer, setAgentAnswer] = useState<AgentAnswer | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);

  async function loadBase() {
    try {
      const [o, i, a, d, c, docs, q, m, mf, mb, w] = await Promise.all([
        getJson<Overview>("/api/v1/overview"),
        getJson<Inventory>("/api/v1/platform/inventory"),
        getJson<AssetsResponse>("/api/v1/assets?limit=180"),
        getJson<DbtSummary>("/api/v1/dbt/summary"),
        getJson<DbtCoverage>("/api/v1/dbt/coverage"),
        getJson<DbtDocs>("/api/v1/dbt/documentation-gaps"),
        getJson<QualitySummary>("/api/v1/quality/summary"),
        getJson<MigrationInventory>("/api/v1/migration/inventory"),
        getJson<MigrationFindings>("/api/v1/migration/findings"),
        getJson<MigrationBlockers>("/api/v1/migration/blockers"),
        getJson<WarehouseStatus>("/api/v1/warehouses"),
      ]);
      setOverview(o); setInventory(i); setAssets(a); setDbtSummary(d); setDbtCoverage(c); setDbtDocs(docs);
      setQuality(q); setMigration(m); setMigrationFindings(mf); setMigrationBlockers(mb); setWarehouses(w);
      setConnected(true); setError(null);
    } catch (cause) {
      setConnected(false);
      setError(cause instanceof Error ? cause.message : "Control plane unavailable");
    }
  }

  useEffect(() => { void loadBase(); }, []);

  useEffect(() => {
    if (active === "Airflow" && (!airflow || !airflowOperations || !airflowFailureLab)) {
      void Promise.all([
        getJson<AirflowInventory>("/api/v1/airflow/inventory"),
        getJson<AirflowOperations>("/api/v1/airflow/operations"),
        getJson<AirflowFailureLab>("/api/v1/airflow/failure-lab"),
      ]).then(([inventoryResult, operationsResult, failureResult]) => {
        setAirflow(inventoryResult);
        setAirflowOperations(operationsResult);
        setAirflowFailureLab(failureResult);
      }).catch((cause) => setError(String(cause)));
    }
  }, [active, airflow, airflowOperations, airflowFailureLab]);

  useEffect(() => {
    if (active === "Reconciliation" && !dataDiff) {
      void getJson<DataDiffDemo>("/api/v1/data-diff/demo").then(setDataDiff).catch((cause) => setError(String(cause)));
    }
  }, [active, dataDiff]);

  async function searchAssets() {
    const query = assetQuery.trim() ? `&query=${encodeURIComponent(assetQuery.trim())}` : "";
    setAssets(await getJson<AssetsResponse>(`/api/v1/assets?limit=300${query}`));
  }

  async function runLineage() {
    if (!lineageNode.trim()) return;
    setLineageBusy(true);
    try {
      const encoded = encodeURIComponent(lineageNode.trim());
      const [l, i] = await Promise.all([
        getJson<LineageResponse>(`/api/v1/lineage/${encoded}?depth=8`),
        getJson<ImpactResponse>(`/api/v1/impact/${encoded}?depth=8`),
      ]);
      setLineage(l); setImpact(i);
    } finally { setLineageBusy(false); }
  }

  async function runSql() {
    setSqlBusy(true);
    try {
      const [review, lineageResult, proposal] = await Promise.all([
        postJson<SqlReview>("/api/v1/sql/review", { sql, dialect }),
        postJson<SqlLineage>("/api/v1/sql/lineage", { sql, dialect }),
        postJson<SqlProposal>("/api/v1/remediation/sql", { sql, dialect }),
      ]);
      setSqlReview(review); setSqlLineage(lineageResult); setSqlProposal(proposal);
    } finally { setSqlBusy(false); }
  }

  async function runReconciliation() {
    const result = await postJson<ReconcileResult>("/api/v1/reconciliation/row-count", {
      source_value: sourceCount, target_value: targetCount, absolute_tolerance: 0, percentage_tolerance: 0,
    });
    setReconcile(result);
  }

  async function askAgent(question = agentQuestion) {
    setAgentQuestion(question);
    setAgentBusy(true);
    try { setAgentAnswer(await postJson<AgentAnswer>("/api/v1/agent/query", { question })); }
    finally { setAgentBusy(false); }
  }

  const title = active === "Overview" ? "Platform control room" : active;
  const mode = overview?.mode ?? "LOCAL_SIMULATION";

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">A</span><div><strong>ADE OS</strong><small>AGENTIC DATA ENGINEERING</small></div></div>
        <div className="mode-chip"><span className={connected ? "live-dot" : "live-dot offline"} />{mode.replaceAll("_", " ")}</div>
        <nav className="nav">
          {NAV.map((item) => (
            <button key={item} onClick={() => setActive(item)} className={active === item ? "nav-item active" : "nav-item"}>
              <span className="nav-glyph">{item.slice(0, 2).toUpperCase()}</span><span>{item}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span>Tool registry</span><strong>{overview?.counts.tools ?? "—"} deterministic tools</strong>
          <small>Analyst mode · read-only</small>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div><p className="eyebrow">AGENTIC DATA ENGINEERING OS · DEMO v0.4</p><h1>{title}</h1></div>
          <div className="top-actions">
            <span className={connected ? "connection good" : "connection bad"}>{connected ? "API connected" : "API unavailable"}</span>
            <button className="ghost" onClick={() => void loadBase()}>Refresh evidence</button>
          </div>
        </header>
        {error && <div className="error-banner"><strong>Control-plane warning</strong><span>{error}</span><code>{API}</code></div>}

        {!overview && active === "Overview" ? <Loading /> : (
          <>
            {active === "Overview" && overview && inventory && <OverviewView overview={overview} inventory={inventory} />}
            {active === "Assets" && <AssetsView assets={assets} query={assetQuery} setQuery={setAssetQuery} search={() => void searchAssets()} />}
            {active === "Lineage" && <LineageView node={lineageNode} setNode={setLineageNode} run={() => void runLineage()} busy={lineageBusy} lineage={lineage} impact={impact} />}
            {active === "SQL Intelligence" && <SqlView sql={sql} setSql={setSql} dialect={dialect} setDialect={setDialect} run={() => void runSql()} busy={sqlBusy} review={sqlReview} lineage={sqlLineage} proposal={sqlProposal} />}
            {active === "dbt" && <DbtView summary={dbtSummary} coverage={dbtCoverage} docs={dbtDocs} />}
            {active === "Airflow" && <AirflowView airflow={airflow} operations={airflowOperations} failureLab={airflowFailureLab} />}
            {active === "Data Quality" && <QualityView quality={quality} />}
            {active === "Reconciliation" && <ReconciliationView source={sourceCount} target={targetCount} setSource={setSourceCount} setTarget={setTargetCount} run={() => void runReconciliation()} result={reconcile} history={quality?.recent_reconciliations ?? []} dataDiff={dataDiff} />}
            {active === "Migration" && <MigrationView inventory={migration} findings={migrationFindings} blockers={migrationBlockers} />}
            {active === "Warehouses" && <WarehousesView warehouses={warehouses} inventory={inventory} />}
            {active === "Connections" && <DomainView title="Connections" eyebrow="CONFIGURED CONNECTION REGISTRY" endpoint="/api/v1/connections" />}
            {active === "Metadata" && <DomainView title="Metadata" eyebrow="INDEXED PLATFORM METADATA" endpoint="/api/v1/metadata/status" />}
            {active === "Data Diff" && <DomainView title="Data Diff" eyebrow="CROSS-SYSTEM PARITY" endpoint="/api/v1/data-diff/demo" />}
            {active === "Cost / FinOps" && <DomainView title="Cost / FinOps" eyebrow="EVIDENCE-BACKED COST INTELLIGENCE" endpoint="/api/v1/finops/report" />}
            {active === "Governance / PII" && <DomainView title="Governance / PII" eyebrow="RBAC & SENSITIVE DATA" endpoint="/api/v1/rbac/audit" />}
            {active === "PR Reviews" && <DomainView title="PR Reviews" eyebrow="DETERMINISTIC REVIEW SURFACE" endpoint="/api/v1/domains" selectKey="review" />}
            {active === "Skills" && <DomainView title="Skills" eyebrow="EXECUTABLE SKILL CATALOG" endpoint="/api/v1/skills/catalog" />}
            {active === "Training" && <DomainView title="Training" eyebrow="LOCAL TRAINING CORPUS" endpoint="/api/v1/training/status" />}
            {active === "Providers" && <DomainView title="Providers" eyebrow="MODEL PROVIDER CONTROL PLANE" endpoint="/api/v1/providers" />}
            {active === "MCP" && <DomainView title="MCP" eyebrow="MODEL CONTEXT PROTOCOL" endpoint="/api/v1/mcp" />}
            {active === "Jobs" && <DomainView title="Jobs" eyebrow="BACKGROUND JOB CONTROL" endpoint="/api/v1/jobs" />}
            {active === "Traces" && <TraceConsole />}
            {active === "Sessions" && <SessionConsole />}
            {active === "Settings / Doctor" && <DomainView title="Settings / Doctor" eyebrow="PLATFORM READINESS" endpoint="/api/v1/platform/health" />}
            {active === "Runs / Evidence" && overview && <EvidenceView overview={overview} quality={quality} />}
            {active === "Investigations" && <InvestigationConsole />}
            {active === "Agent" && <AgentView question={agentQuestion} setQuestion={setAgentQuestion} ask={askAgent} busy={agentBusy} answer={agentAnswer} />}
          </>
        )}
      </section>
    </main>
  );
}

function OverviewView({ overview, inventory }: { overview: Overview; inventory: Inventory }) {
  const gaugeStyle = { "--score": `${overview.health_score * 3.6}deg` } as CSSProperties;
  return (
    <>
      <section className="metrics">
        <Metric label="Platform health" value={<span className="metric-inline"><i className="health-dot" />{overview.health_score}/100</span>} sub={overview.health_status} />
        <Metric label="Source assets" value={overview.counts.sources} sub={`${overview.counts.oracle_tables} Oracle · ${overview.counts.postgres_tables} Postgres · ${overview.counts.file_feeds} feeds`} />
        <Metric label="Airflow" value={overview.counts.airflow_dags} sub="DAGs discovered by AST" />
        <Metric label="dbt" value={overview.counts.dbt_models} sub={`${overview.counts.dbt_tests} tests · ${overview.counts.dbt_snapshots} snapshots`} />
        <Metric label="Migration" value={overview.migration.engine} sub={`${overview.migration.blockers} blockers`} />
      </section>
      <div className="two-col wide-left">
        <Panel title="Evidence-backed platform health" eyebrow="CURRENT STATE">
          <div className="health-layout">
            <div className="health-gauge" style={gaugeStyle}><div><strong>{overview.health_score}</strong><span>/100</span></div></div>
            <div className="health-checks">
              {Object.entries(overview.health_components).map(([name, check]) => (
                <div className="health-row" key={name}><span>{name.replaceAll("_", " ")}</span><StatusBadge status={check.status} /><small>{check.detail}</small></div>
              ))}
            </div>
          </div>
        </Panel>
        <Panel title="Recent findings" eyebrow="EVIDENCE">
          <div className="finding-list">
            {overview.findings.length ? overview.findings.map((finding, index) => (
              <div className="finding" key={`${finding.title}-${index}`}>
                <span className={`severity ${finding.severity}`} /> <div><strong>{finding.title}</strong><p>{finding.detail}</p></div><small>{finding.source}</small>
              </div>
            )) : <Empty>No current warnings or failures.</Empty>}
          </div>
        </Panel>
      </div>
      <div className="three-col">
        <Panel title="Sources" eyebrow="INGESTION">
          <div className="stacked-list">
            <KeyValue label="Oracle PMS" value={overview.counts.oracle_tables} status="LOCAL SIMULATION" />
            <KeyValue label="PostgreSQL booking" value={overview.counts.postgres_tables} status="LOCAL SIMULATION" />
            <KeyValue label="File feeds" value={overview.counts.file_feeds} status="READY" />
          </div>
        </Panel>
        <Panel title="dbt assurance" eyebrow="TRANSFORMATION">
          <div className="coverage-head"><strong>{overview.dbt_coverage.coverage_pct}%</strong><span>models protected by tests</span></div>
          <div className="progress"><i style={{ width: `${overview.dbt_coverage.coverage_pct}%` }} /></div>
          <div className="mini-stats"><span>{overview.dbt_coverage.tested_count} tested</span><span>{overview.dbt_coverage.untested_count} untested</span></div>
        </Panel>
        <Panel title="Snowflake target" eyebrow="WAREHOUSE">
          <div className="stacked-list">
            <KeyValue label="Static objects" value={compact(inventory.snowflake.objects ?? {})} status="INDEXED" />
            <KeyValue label="Live connection" value={inventory.snowflake.live_status?.includes("AVAILABLE") ? "Configured" : "Not configured"} status={inventory.snowflake.live_status?.includes("AVAILABLE") ? "PASS" : "SKIP"} />
            <KeyValue label="Execution mode" value="Read-only demo" status="SAFE" />
          </div>
        </Panel>
      </div>
    </>
  );
}

function KeyValue({ label, value, status }: { label: string; value: ReactNode; status: string }) {
  return <div className="key-value"><div><span>{label}</span><strong>{value}</strong></div><StatusBadge status={status} /></div>;
}

function AssetsView({ assets, query, setQuery, search }: { assets: AssetsResponse | null; query: string; setQuery: (value: string) => void; search: () => void }) {
  return (
    <Panel title="Cross-system asset catalog" eyebrow="METADATA GRAPH" actions={
      <div className="search"><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && search()} placeholder="Search reservation, guest, payment…" /><button onClick={search}>Search</button></div>
    }>
      {!assets ? <Loading /> : <>
        <div className="inline-summary"><span>{assets.total} matches</span><span>{assets.returned} returned</span><span>{Object.keys(assets.node_types).length} asset types</span></div>
        <div className="table-wrap"><table><thead><tr><th>Asset</th><th>Type</th><th>System / layer</th><th>Evidence</th></tr></thead><tbody>
          {assets.items.map((asset) => <tr key={asset.node_id}><td><strong>{asset.name}</strong><small>{asset.node_id.slice(0, 18)}</small></td><td><span className="type-pill">{asset.kind}</span></td><td>{compact(asset.properties.system ?? asset.properties.layer ?? asset.properties.resource_type)}</td><td className="mono">{compact(asset.properties.file ?? asset.properties.relation_name ?? "metadata graph")}</td></tr>)}
        </tbody></table></div>
      </>}
    </Panel>
  );
}

function LineageView({ node, setNode, run, busy, lineage, impact }: { node: string; setNode: (value: string) => void; run: () => void; busy: boolean; lineage: LineageResponse | null; impact: ImpactResponse | null }) {
  const upstream = lineage ? [...lineage.upstream].sort((a, b) => (b.depth ?? 0) - (a.depth ?? 0)).slice(0, 12) : [];
  const downstream = lineage ? [...lineage.downstream].sort((a, b) => (a.depth ?? 0) - (b.depth ?? 0)).slice(0, 16) : [];
  return (
    <>
      <Panel title="Lineage explorer" eyebrow="CROSS-SYSTEM GRAPH" actions={<div className="search"><input value={node} onChange={(e) => setNode(e.target.value)} placeholder="fact_reservation" /><button onClick={run} disabled={busy}>{busy ? "Tracing…" : "Trace"}</button></div>}>
        {!lineage ? <Empty>Trace an asset to calculate real upstream and downstream dependencies.</Empty> : <div className="lineage-scroll"><div className="lineage-flow">
          {upstream.map((item) => <LineageNode key={item.node_id} node={item} />)}
          <span className="flow-arrow">→</span><LineageNode node={lineage.asset} focus /><span className="flow-arrow">→</span>
          {downstream.map((item) => <LineageNode key={item.node_id} node={item} />)}
        </div></div>}
      </Panel>
      <div className="two-col">
        <Panel title="Impact analysis" eyebrow="WHAT BREAKS IF THIS CHANGES?">
          {!impact ? <Empty>No impact analysis yet.</Empty> : <div className="impact-grid">
            <div><span>Severity</span><StatusBadge status={impact.severity} /></div>
            <div><span>Downstream assets</span><strong>{impact.downstream.length}</strong></div>
            <div><span>Affected marts</span><strong>{impact.affected_marts.length}</strong></div>
            <div><span>Affected tests</span><strong>{impact.affected_tests.length}</strong></div>
          </div>}
        </Panel>
        <Panel title="Affected marts" eyebrow="BUSINESS EXPOSURE">
          {!impact?.affected_marts.length ? <Empty>No mart impacts found.</Empty> : <div className="chip-list">{impact.affected_marts.map((item) => <span key={item.node_id}>{item.name}</span>)}</div>}
        </Panel>
      </div>
    </>
  );
}

function LineageNode({ node, focus = false }: { node: TraversalNode | AssetNode; focus?: boolean }) {
  return <div className={focus ? "lineage-node focus" : "lineage-node"}><span>{node.kind}</span><strong>{node.name}</strong>{"depth" in node && node.depth ? <small>depth {node.depth}</small> : null}</div>;
}

function SqlView({ sql, setSql, dialect, setDialect, run, busy, review, lineage, proposal }: { sql: string; setSql: (value: string) => void; dialect: string; setDialect: (value: string) => void; run: () => void; busy: boolean; review: SqlReview | null; lineage: SqlLineage | null; proposal: SqlProposal | null }) {
  return (
    <>
      <Panel title="SQL intelligence workspace" eyebrow="SQLGLOT AST ENGINE" actions={<div className="sql-actions"><select value={dialect} onChange={(e) => setDialect(e.target.value)}>{["snowflake","bigquery","redshift","postgres","oracle","spark","duckdb"].map((item) => <option key={item}>{item}</option>)}</select><button className="primary" onClick={run} disabled={busy}>{busy ? "Analyzing…" : "Analyze SQL"}</button></div>}>
        <textarea className="sql-editor" value={sql} onChange={(event) => setSql(event.target.value)} spellCheck={false} />
      </Panel>
      <div className="two-col equal">
        <Panel title="Deterministic findings" eyebrow="RULE ENGINE">
          {!review ? <Empty>Run the analyzer to inspect safety, performance, and portability findings.</Empty> : <>
            <div className="inline-summary"><StatusBadge status={review.status} /><span>{review.findings.length} findings</span><span>{review.tables.length} tables</span></div>
            <div className="finding-table">{review.findings.map((finding, index) => <div className="sql-finding" key={`${finding.rule_id}-${index}`}><StatusBadge status={finding.severity} /><div><strong>{finding.rule_id} · {finding.message}</strong><p>{finding.recommendation ?? "No remediation text supplied."}</p><small>{finding.line ? `line ${finding.line}` : "AST-level"} · {finding.evidence ?? "deterministic evidence"}</small></div></div>)}</div>
          </>}
        </Panel>
        <Panel title="Column lineage" eyebrow="VALUE LINEAGE">
          {!lineage ? <Empty>Column mappings appear here after analysis.</Empty> : lineage.parseable ? <div className="mapping-list">
            {(lineage.mappings ?? []).map((mapping) => <div className="mapping" key={mapping.target_column}><div><span>OUTPUT</span><strong>{mapping.target_column}</strong></div><i>←</i><div className="mapping-sources">{mapping.sources.length ? mapping.sources.map((source) => <span key={`${source.table}.${source.column}`}>{source.table}.{source.column}</span>) : <span>UNRESOLVED</span>}</div><StatusBadge status={mapping.resolved ? "PASS" : "PARTIAL"} /></div>)}
          </div> : <div className="error-box">{lineage.error}</div>}
        </Panel>
      </div>
      <Panel title="Repair proposal" eyebrow="PROPOSE ONLY · BUILDER APPROVAL REQUIRED">
        {!proposal ? <Empty>Analyze SQL to generate bounded remediation proposals.</Empty> : <div className="proposal-list">
          <div className="inline-summary"><StatusBadge status={proposal.status} /><span>{proposal.proposals.length} proposals</span><span>Applied: {String(proposal.applied)}</span></div>
          {proposal.proposals.slice(0, 8).map((item, index) => <div className="proposal" key={`${item.rule_id}-${index}`}><strong>{item.rule_id} · {item.problem}</strong><p>{item.proposal}</p><small>{item.automatic_edit ? "automatic edit candidate" : "human-reviewed proposal only"}</small></div>)}
        </div>}
      </Panel>
    </>
  );
}

function DbtView({ summary, coverage, docs }: { summary: DbtSummary | null; coverage: DbtCoverage | null; docs: DbtDocs | null }) {
  if (!summary || !coverage || !docs) return <Loading />;
  return (
    <>
      <section className="metrics four"><Metric label="Models" value={summary.resource_counts.model ?? 0} /><Metric label="Tests" value={summary.resource_counts.test ?? 0} /><Metric label="Snapshots" value={summary.resource_counts.snapshot ?? 0} /><Metric label="Sources" value={summary.resource_counts.source ?? 0} /></section>
      <div className="two-col equal">
        <Panel title="Test coverage" eyebrow="DBT ASSURANCE"><div className="coverage-hero"><strong>{coverage.coverage_pct}%</strong><span>{coverage.tested_count}/{coverage.models} models protected</span></div><div className="progress tall"><i style={{ width: `${coverage.coverage_pct}%` }} /></div><h3>Untested models</h3><div className="chip-list scroll-chips">{coverage.untested_models.slice(0, 30).map((item) => <span key={item}>{item}</span>)}{!coverage.untested_models.length && <StatusBadge status="PASS" />}</div></Panel>
        <Panel title="Documentation gaps" eyebrow="MODEL GOVERNANCE"><div className="impact-grid"><div><span>Model gaps</span><strong>{docs.model_gap_count}</strong></div><div><span>Column gaps</span><strong>{docs.column_gap_count}</strong></div></div><div className="table-wrap compact-table"><table><thead><tr><th>Model</th><th>Column</th></tr></thead><tbody>{docs.missing_column_descriptions.slice(0, 20).map((item) => <tr key={`${item.model}.${item.column}`}><td>{item.model}</td><td>{item.column}</td></tr>)}</tbody></table></div></Panel>
      </div>
      <Panel title="Artifact state" eyebrow="DBT TARGET"><div className="chip-list">{Object.entries(summary.artifacts).map(([name, present]) => <span key={name} className={present ? "chip-good" : "chip-muted"}>{name}: {present ? "FOUND" : "MISSING"}</span>)}</div></Panel>
    </>
  );
}

function AirflowView({ airflow, operations, failureLab }: { airflow: AirflowInventory | null; operations: AirflowOperations | null; failureLab: AirflowFailureLab | null }) {
  if (!airflow || !operations || !failureLab) return <Loading text="Parsing Airflow DAGs and reliability evidence…" />;
  return (
    <>
      <section className="metrics four"><Metric label="DAGs" value={airflow.dag_count} /><Metric label="Pipeline health" value={operations.health.score} sub={String(operations.health.status)} /><Metric label="Retry gaps" value={operations.retry.missing_or_zero_count} /><Metric label="Backfill risks" value={operations.backfill.risk_count} /></section>
      <div className="two-col equal">
        <Panel title="Operational readiness" eyebrow="STATIC RELIABILITY ANALYSIS">
          <div className="impact-grid"><div><span>Retry coverage</span><strong>{operations.retry.configured_count}/{airflow.dag_count}</strong></div><div><span>Connections</span><strong>{operations.connections.connection_count}</strong></div><div><span>Catchup enabled</span><strong>{operations.schedule.catchup_enabled.length}</strong></div><div><span>Runtime API</span><StatusBadge status="SKIP" /></div></div>
          <p className="note">{operations.health.live_runtime}</p>
        </Panel>
        <Panel title="Failure lab" eyebrow={failureLab.mode}>
          <div className="failure-lab"><div><span>DAG / task</span><strong>{failureLab.event.dag_id} · {failureLab.event.task_id}</strong></div><div><span>State</span><StatusBadge status={failureLab.event.state} /></div><div><span>Probable cause</span><strong>{failureLab.diagnosis.cause}</strong></div><div><span>Confidence</span><strong>{Math.round(failureLab.diagnosis.confidence * 100)}%</strong></div><p>{failureLab.diagnosis.recommended_action}</p></div>
        </Panel>
      </div>
      <Panel title="Airflow DAG inventory" eyebrow="STATIC AST INTELLIGENCE">
        <div className="table-wrap"><table><thead><tr><th>DAG</th><th>Schedule</th><th>Tasks</th><th>Retries</th><th>Catchup</th><th>Connections</th><th>Source</th></tr></thead><tbody>
          {airflow.details.map((dag) => <tr key={dag.dag_id}><td><strong>{dag.dag_id}</strong><small>{dag.file.split("/").slice(-2).join("/")}</small></td><td>{dag.schedule ?? "—"}</td><td>{dag.tasks.length}</td><td>{dag.retries ?? "—"}</td><td><StatusBadge status={dag.catchup === false ? "PASS" : dag.catchup === true ? "WARN" : "SKIP"} /></td><td>{dag.connections.join(", ") || "—"}</td><td>{dag.source ?? "orchestration"}</td></tr>)}
        </tbody></table></div>
      </Panel>
      <AirflowDeepPanels />
    </>
  );
}

function AirflowDeepPanels() {
  return <div className="two-col equal">
    <DomainView title="Airflow 3 Assets & events" eyebrow="ASSETS / DATASETS" endpoint="/api/v1/airflow/assets" />
    <DomainView title="Airflow capacity" eyebrow="POOLS / QUEUES / CONCURRENCY" endpoint="/api/v1/airflow/capacity" />
    <DomainView title="Upgrade intelligence" eyebrow="TASK SDK / AIRFLOW 3" endpoint="/api/v1/airflow/upgrade" />
    <DomainView title="Airflow security" eyebrow="SECRETS / XCOM / BUNDLES" endpoint="/api/v1/airflow/security" />
  </div>;
}

function QualityView({ quality }: { quality: QualitySummary | null }) {
  if (!quality) return <Loading />;
  return (
    <>
      <section className="metrics four"><Metric label="Quality runs" value={quality.run_count} /><Metric label="Checks" value={quality.result_count} /><Metric label="Failures" value={quality.status_counts.FAIL ?? 0} /><Metric label="Reconciliations" value={quality.reconciliation_count} /></section>
      <Panel title="Recent quality evidence" eyebrow="SQLITE EVIDENCE STORE">
        {!quality.recent_results.length ? <Empty>Run <code>make demo-data</code> to seed deterministic local evidence.</Empty> : <div className="table-wrap"><table><thead><tr><th>Check</th><th>Asset</th><th>Type</th><th>Observed</th><th>Expected</th><th>Status</th></tr></thead><tbody>
          {quality.recent_results.map((item) => <tr key={item.result_id}><td><strong>{item.check_id}</strong><small>{item.layer} · {item.system}</small></td><td>{item.asset}</td><td>{item.check_type}</td><td>{compact(item.observed_value)}</td><td>{compact(item.expected_value)}</td><td><StatusBadge status={item.status} /></td></tr>)}
        </tbody></table></div>}
      </Panel>
    </>
  );
}

function ReconciliationView({ source, target, setSource, setTarget, run, result, history, dataDiff }: { source: number; target: number; setSource: (value: number) => void; setTarget: (value: number) => void; run: () => void; result: ReconcileResult | null; history: ReconciliationHistory[]; dataDiff: DataDiffDemo | null }) {
  return (
    <>
      <Panel title="Source-target reconciliation" eyebrow="FAIL-CLOSED DATA PARITY">
        <div className="reconcile-form"><label>Source rows<input type="number" value={source} onChange={(e) => setSource(Number(e.target.value))} /></label><span>vs</span><label>Target rows<input type="number" value={target} onChange={(e) => setTarget(Number(e.target.value))} /></label><button className="primary" onClick={run}>Compare</button><button className="ghost" onClick={() => { setSource(10000); setTarget(10000); }}>Clean fixture</button></div>
        {result && <div className={result.status === "PASS" ? "reconcile-result pass" : "reconcile-result fail"}><div><span>Result</span><StatusBadge status={result.status} /></div><div><span>Difference</span><strong>{result.difference}</strong></div><div><span>Difference %</span><strong>{result.difference_pct.toFixed(4)}%</strong></div><div><span>Tolerance</span><strong>{result.tolerance.absolute} rows</strong></div></div>}
      </Panel>
      <Panel title="DuckDB keyed data diff" eyebrow="LOCAL SIMULATION · REAL QUERY ENGINE">
        {!dataDiff ? <Loading text="Running local source-target diff…" /> : <div className="data-diff">
          <div className="inline-summary"><StatusBadge status={dataDiff.status} /><span>{dataDiff.source}</span><span>{dataDiff.target}</span></div>
          <div className="impact-grid"><div><span>Matches</span><strong>{dataDiff.rows.counts.matches}</strong></div><div><span>Changed</span><strong>{dataDiff.rows.counts.changed}</strong></div><div><span>Missing</span><strong>{dataDiff.rows.counts.missing}</strong></div><div><span>Extra</span><strong>{dataDiff.rows.counts.extra}</strong></div></div>
          <div className="chip-list">{dataDiff.aggregates.map((item) => <span key={item.column}>{item.aggregate}({item.column}): {item.source_value} → {item.target_value} · {item.status}</span>)}</div>
        </div>}
      </Panel>
      <Panel title="Persisted reconciliation history" eyebrow="QUALITY EVIDENCE">
        {!history.length ? <Empty>No persisted reconciliation evidence yet.</Empty> : <div className="table-wrap compact-table"><table><thead><tr><th>Metric</th><th>Source</th><th>Target</th><th>Difference</th><th>Status</th><th>Timestamp</th></tr></thead><tbody>{history.map((item) => <tr key={item.result_id}><td>{item.metric}</td><td>{compact(item.result.source_value)}</td><td>{compact(item.result.target_value)}</td><td>{compact(item.result.difference)}</td><td><StatusBadge status={item.status} /></td><td>{new Date(item.timestamp).toLocaleString()}</td></tr>)}</tbody></table></div>}
      </Panel>
    </>
  );
}

function MigrationView({ inventory, findings, blockers }: { inventory: MigrationInventory | null; findings: MigrationFindings | null; blockers: MigrationBlockers | null }) {
  if (!inventory || !findings || !blockers) return <Loading />;
  return (
    <>
      <section className="metrics four"><Metric label="Models discovered" value={inventory.models} /><Metric label="Source dialect" value={inventory.source_dialect} /><Metric label="Target dialect" value={inventory.target_dialect} /><Metric label="Blockers" value={blockers.count} /></section>
      <div className="two-col equal">
        <Panel title="ShiftForge findings" eyebrow="DETERMINISTIC MIGRATION ENGINE">{findings.count ? <pre className="json-panel">{JSON.stringify(findings.findings.slice(0, 8), null, 2)}</pre> : <Empty>No conversion findings in the current fixture.</Empty>}</Panel>
        <Panel title="Review blockers" eyebrow="HUMAN-IN-THE-LOOP">{blockers.count ? <pre className="json-panel">{JSON.stringify(blockers.blockers.slice(0, 8), null, 2)}</pre> : <div className="success-box"><StatusBadge status="PASS" /><strong>No blocking findings</strong><span>Current fixture is auto-convertible or review-safe.</span></div>}</Panel>
      </div>
    </>
  );
}

function WarehousesView({ warehouses, inventory }: { warehouses: WarehouseStatus | null; inventory: Inventory | null }) {
  if (!warehouses) return <Loading />;
  return (
    <>
      <Panel title="Warehouse adapter matrix" eyebrow="CONNECTIVITY & SIMULATION">
        <div className="table-wrap"><table><thead><tr><th>Warehouse</th><th>Adapter</th><th>Driver</th><th>Credentials</th><th>Live</th><th>Simulation</th><th>Status</th></tr></thead><tbody>{warehouses.adapters.map((item) => <tr key={item.name}><td><strong>{item.name}</strong></td><td>{item.adapter_available ? "Available" : "Roadmap"}</td><td>{item.driver_installed ? "Installed" : "Not installed"}</td><td>{item.credentials_configured ? "Configured" : "Not configured"}</td><td>{item.live_connectivity}</td><td>{item.simulation_available ? "Yes" : "No"}</td><td><StatusBadge status={item.status} /></td></tr>)}</tbody></table></div>
      </Panel>
      {inventory && <Panel title="Snowflake static inventory" eyebrow="REPOSITORY METADATA"><div className="chip-list">{Object.entries(inventory.snowflake.objects ?? {}).map(([name, count]) => <span key={name}>{name.replaceAll("_", " ")}: {count}</span>)}</div><p className="note">{inventory.snowflake.live_status}</p></Panel>}
    </>
  );
}

function EvidenceView({ overview, quality }: { overview: Overview; quality: QualitySummary | null }) {
  return (
    <div className="two-col equal">
      <Panel title="Runtime evidence" eyebrow="PLATFORM STATE"><div className="stacked-list">{Object.entries(overview.health_components).map(([name, item]) => <KeyValue key={name} label={name.replaceAll("_", " ")} value={item.detail} status={item.status} />)}</div></Panel>
      <Panel title="Quality evidence store" eyebrow="LOCAL SQLITE"><div className="impact-grid"><div><span>Runs</span><strong>{quality?.run_count ?? 0}</strong></div><div><span>Checks</span><strong>{quality?.result_count ?? 0}</strong></div><div><span>Recon results</span><strong>{quality?.reconciliation_count ?? 0}</strong></div><div><span>Failures</span><strong>{quality?.status_counts.FAIL ?? 0}</strong></div></div><p className="note">Every product-state answer should point back to deterministic tools or persisted evidence.</p></Panel>
    </div>
  );
}

function AgentView({ question, setQuestion, ask, busy, answer }: { question: string; setQuestion: (value: string) => void; ask: (question?: string) => Promise<void>; busy: boolean; answer: AgentAnswer | null }) {
  const samples = ["Why is fact_reservation unhealthy?", "What depends on stg_oracle_reservation?", "Which DAG loads reservations?", "What dbt models have no tests?", "Show migration blockers."];
  return (
    <>
      <Panel title="Deterministic agent console" eyebrow="TOOLS ARE THE SOURCE OF TRUTH">
        <div className="agent-input"><textarea value={question} onChange={(e) => setQuestion(e.target.value)} /><button className="primary" onClick={() => void ask()} disabled={busy}>{busy ? "Resolving…" : "Ask with tools"}</button></div>
        <div className="sample-prompts">{samples.map((sample) => <button key={sample} onClick={() => void ask(sample)}>{sample}</button>)}</div>
      </Panel>
      {answer && <div className="two-col equal"><Panel title="Result" eyebrow="DETERMINISTIC ANSWER"><pre className="json-panel tall-json">{JSON.stringify(answer.result, null, 2)}</pre></Panel><Panel title="Evidence" eyebrow="AUDIT TRAIL"><div className="stacked-list"><KeyValue label="Tools used" value={answer.evidence.tools_used.join(", ") || "No tool matched"} status={answer.evidence.tools_used.length ? "PASS" : "WARN"} /><KeyValue label="Data sources" value={answer.evidence.data_sources.join(", ") || "—"} status="EVIDENCE" /><KeyValue label="Router" value={answer.evidence.mode} status="READ ONLY" /><KeyValue label="Timestamp" value={new Date(answer.evidence.timestamp).toLocaleString()} status="RECORDED" /></div></Panel></div>}
    </>
  );
}

function DomainView({ title, eyebrow, endpoint, selectKey }: { title: string; eyebrow: string; endpoint: string; selectKey?: string }) {
  const [data, setData] = useState<unknown>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setLoadError(null);
    void getJson<unknown>(endpoint).then((value) => {
      if (cancelled) return;
      if (selectKey && value && typeof value === "object" && selectKey in (value as RecordValue)) {
        setData((value as RecordValue)[selectKey]);
      } else {
        setData(value);
      }
    }).catch((cause) => {
      if (!cancelled) setLoadError(cause instanceof Error ? cause.message : String(cause));
    });
    return () => { cancelled = true; };
  }, [endpoint, selectKey]);
  return <Panel title={title} eyebrow={eyebrow}>
    {loadError ? <div className="error-box">{loadError}</div> : data === null ? <Loading text={`Loading ${title.toLowerCase()} evidence…`} /> :
      <pre className="json-panel tall-json">{JSON.stringify(data, null, 2)}</pre>}
  </Panel>;
}

