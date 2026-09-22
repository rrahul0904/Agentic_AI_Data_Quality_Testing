"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import DraftShell from "./DraftShell";
import styles from "./workflow.module.css";
import ScopedLink from "./components/ScopedLink";
import { scopedApiUrl } from "../lib/client-workspace";
import { integrationConnectionState } from "../lib/ui-contracts";
import { ErrorState, PageHeader, StatusBadge } from "./components/ui";

type Payload = Record<string, unknown>;
type Operations = {
  generatedAt: string;
  workspace: { projectId: string; environment: string; name: string };
  source_table_scope_id?: string | null;
  integrations: Record<string, Payload>;
  analysis: Payload;
  plan: Payload;
  runs: Payload;
  incidents: Payload;
  alerts: Payload;
  agent: Payload;
  source?: string;
};

type AttentionFilter = "ALL" | "BLOCKED" | "REVIEW" | "APPROVAL";
type AttentionRow = {
  id: string;
  priority: "HIGH" | "MEDIUM" | "LOW";
  issue: string;
  detail: string;
  scope: string;
  status: "BLOCKED" | "REVIEW" | "APPROVAL" | "EXCLUDED";
  lastSeen: string;
  action: string;
  href: string;
};

function asPayload(value: unknown): Payload {
  return value && typeof value === "object" ? value as Payload : {};
}

function asNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function display(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function formatDate(value: unknown, fallback = "Not available"): string {
  if (!value) return fallback;
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? fallback : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function label(value: unknown): string {
  return display(value, "UNKNOWN").replace(/_/g, " ");
}

function statusTone(value: unknown): "good" | "warn" | "bad" | "neutral" {
  const state = display(value, "NOT_CHECKED").toUpperCase();
  if (["PASS", "PASSED", "COMPLETED", "VERIFIED", "READY", "HEALTHY"].includes(state)) return "good";
  if (["QUEUED", "SUBMITTING", "RUNNING", "MONITORING", "VERIFYING", "PENDING", "AWAITING_APPROVAL", "AWAITING_CONTINUATION", "REVIEW", "STALE"].includes(state)) return "warn";
  if (["FAIL", "FAILED", "ERROR", "BLOCKED", "UNCERTAIN", "OUTCOME_UNKNOWN", "REJECTED"].includes(state)) return "bad";
  return "neutral";
}

function plural(count: number, singular: string, multiple = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : multiple}`;
}

function connectionSummary(passing: number, total: number): string {
  if (!total) return "NOT CHECKED";
  return `${passing} healthy · ${Math.max(0, total - passing)} needs review`;
}

function persistedRunTime(run?: Payload): string {
  return formatDate(run?.completed_at ?? run?.started_at);
}

function integrationEndpoint(value: Payload): string {
  const endpoint = value.base_url ?? value.baseUrl ?? value.airflow_base_url ?? value.url ?? value.endpoint;
  return typeof endpoint === "string" && endpoint.trim() ? endpoint : "Endpoint not returned by the current adapter";
}

export default function HomePage() {
  const [data, setData] = useState<Operations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshState, setRefreshState] = useState<"SNAPSHOT" | "REFRESHING" | "LIVE" | "ERROR">("SNAPSHOT");
  const [attentionFilter, setAttentionFilter] = useState<AttentionFilter>("ALL");
  const [attentionPage, setAttentionPage] = useState(1);
  const [resultPage, setResultPage] = useState(1);
  const loadingRef = useRef(false);
  const ATTENTION_PAGE_SIZE = 7;
  const RESULT_PAGE_SIZE = 8;

  const loadSummary = async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(scopedApiUrl("/api/operations?mode=summary"), { cache: "no-store", signal: AbortSignal.timeout(3000) });
      if (!response.ok) throw new Error("Persisted operations snapshot unavailable");
      const value = await response.json() as Operations;
      setData(value);
      setRefreshState("SNAPSHOT");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load operations");
    } finally {
      loadingRef.current = false;
      setBusy(false);
    }
  };

  const loadLiveEvidence = async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setBusy(true);
    setRefreshState("REFRESHING");
    setError(null);
    try {
      const response = await fetch(scopedApiUrl("/api/operations"), { cache: "no-store", signal: AbortSignal.timeout(9000) });
      const value = await response.json() as Operations & { error?: string };
      if (!response.ok) throw new Error(value.error || "Live operations refresh unavailable");
      setData(value);
      setRefreshState("LIVE");
    } catch (reason) {
      setRefreshState("ERROR");
      setError(reason instanceof Error ? reason.message : "Live operations refresh unavailable");
    } finally {
      loadingRef.current = false;
      setBusy(false);
    }
  };

  useEffect(() => {
    let active = true;
    void loadSummary().finally(() => {
      if (active) void loadLiveEvidence();
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const refresh = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadLiveEvidence();
    }, 30_000);
    return () => window.clearInterval(refresh);
  }, []);

  const integrations = data ? Object.entries(data.integrations) : [];
  const latestRuns = Array.isArray(data?.runs.items) ? data.runs.items as Payload[] : [];
  const incidents = Array.isArray(data?.incidents.items) ? data.incidents.items as Payload[] : [];
  const alerts = Array.isArray(data?.alerts.items) ? data.alerts.items as Payload[] : [];
  const latestRun = latestRuns[0];
  const planSummary = asPayload(data?.plan.summary);
  const analysisSummary = asPayload(data?.analysis.summary);
  const latestRunSummary = asPayload(latestRun?.summary);
  const runStatusCounts = asPayload(latestRunSummary.status_counts);
  const runExecuted = asNumber(latestRunSummary.executed, latestRun ? asNumber(data?.plan && planSummary.enabled_check_count, 0) : 0);
  const passedChecks = asNumber(runStatusCounts.PASS ?? runStatusCounts.PASSED);
  const failedChecks = asNumber(runStatusCounts.FAIL ?? runStatusCounts.FAILED);
  const erroredChecks = asNumber(runStatusCounts.ERROR ?? runStatusCounts.ERRORED);
  const hasExecutionEvidence = Boolean(latestRun);
  const hasActiveScope = typeof data?.source_table_scope_id === "string" && data.source_table_scope_id.length > 0;
  const openIncidents = hasExecutionEvidence
    ? (Array.isArray(data?.incidents.open_items)
      ? data.incidents.open_items as Payload[]
      : incidents.filter((item) => !["RESOLVED", "CERTIFIED"].includes(display(item.status).toUpperCase())))
    : [];
  const openAlerts = hasExecutionEvidence
    ? (Array.isArray(data?.alerts.open_items)
      ? data.alerts.open_items as Payload[]
      : alerts.filter((item) => display(item.status).toUpperCase() === "OPEN"))
    : [];
  const passingConnections = integrations.filter(([, value]) => integrationConnectionState(value) === "PASSING").length;
  const totalConnections = integrations.length;
  const latestConnectionCheck = integrations.reduce<string | undefined>((latest, [, value]) => {
    const candidate = value.last_connection_check ?? value.last_refreshed ?? value.testedAt ?? value.last_tested_at;
    if (!candidate) return latest;
    if (!latest) return String(candidate);
    return new Date(String(candidate)).getTime() > new Date(latest).getTime() ? String(candidate) : latest;
  }, undefined);
  const unmappedSources = asNumber(planSummary.unmapped_source_count);
  const reviewRequired = asNumber(planSummary.review_required_count);
  const mappedAssets = asNumber(planSummary.mapping_count);
  const discoveredAssets = asNumber(analysisSummary.assets, asNumber(analysisSummary.node_count));
  const coverageDenominator = mappedAssets + unmappedSources;
  const analysisStatus = display(data?.analysis.status, "NOT_CHECKED").toUpperCase();
  const analysisChecked = ["PASS", "PASSED", "COMPLETED", "READY", "AVAILABLE"].includes(analysisStatus);
  const coveragePercent = analysisChecked && coverageDenominator ? Math.round((mappedAssets / coverageDenominator) * 100) : 0;
  const consoleLocation = typeof window === "undefined" ? "this browser" : window.location.host;
  const airflow = data?.integrations?.airflow;

  const attentionRows = useMemo<AttentionRow[]>(() => {
    if (!data) return [];
    const rows: AttentionRow[] = [];
    const runDate = display(latestRun?.completed_at ?? latestRun?.started_at, "Not available");
    if (hasActiveScope && !latestRun) {
      rows.push({ id: "no-execution", priority: "MEDIUM", issue: "No pipeline or quality execution evidence", detail: "Connections, discovery, mappings, and rules are configuration evidence only until a run produces results.", scope: "Execution readiness", status: "REVIEW", lastSeen: "Not available", action: "Open run results", href: "/test-plan?view=execution&mode=manage&tab=run#run-results" });
    }
    if (latestRun && (failedChecks > 0 || erroredChecks > 0 || display(latestRun.status).toUpperCase() !== "PASS")) {
      const runId = display(latestRun.run_id, "");
      rows.push({ id: "latest-run", priority: "HIGH", issue: "Latest quality run needs review", detail: `${plural(runExecuted, "check")} executed; ${failedChecks} failed and ${erroredChecks} errored.`, scope: `Plan revision ${display(data.plan.revision)}`, status: "REVIEW", lastSeen: runDate, action: "View exact run", href: runId ? `/actions?run_id=${encodeURIComponent(runId)}#execution-monitor` : "/test-plan?view=execution&mode=manage&tab=run#run-results" });
    }
    if (openIncidents.length) {
      const newestIncident = openIncidents[0];
      const incidentId = display(newestIncident.incident_id ?? newestIncident.id, "");
      rows.push({ id: "open-incidents", priority: "HIGH", issue: "Open quality incidents", detail: "Incidents are created from failed persisted plan executions.", scope: plural(openIncidents.length, "incident"), status: "REVIEW", lastSeen: display(newestIncident.created_at ?? newestIncident.updated_at, "Not available"), action: "Open exact incident", href: incidentId ? `/incidents?incident_id=${encodeURIComponent(incidentId)}#incident-${encodeURIComponent(incidentId)}` : "/incidents" });
    }
    integrations.filter(([, value]) => integrationConnectionState(value) === "ATTENTION").forEach(([name, value]) => {
      const connectionId = display(value.connection_id ?? value.id ?? name, name);
      rows.push({ id: `connection-${name}`, priority: "HIGH", issue: `${name.toUpperCase()} connection requires attention`, detail: display(value.reason ?? value.runtime_error ?? value.detail, "The adapter did not return a passing health state."), scope: "Connection health", status: "BLOCKED", lastSeen: display(value.last_refreshed ?? value.testedAt, "Not available"), action: "Open connection", href: `/register-project?phase=connections&connection_id=${encodeURIComponent(connectionId)}&connection_kind=${encodeURIComponent(name)}#connection-${encodeURIComponent(connectionId)}` });
    });
    if (reviewRequired > 0) {
      rows.push({ id: "review-checks", priority: "MEDIUM", issue: "Quality checks require confirmation", detail: "Review the exact revision, tests, thresholds, and environment before execution.", scope: `Plan revision ${display(data.plan.revision)}`, status: "APPROVAL", lastSeen: display(data.plan.approved_at, "Not available"), action: "Open review plan", href: "/test-plan?view=contracts&mode=manage" });
    }
    if (unmappedSources > 0) {
      rows.push({ id: "unmapped-sources", priority: "MEDIUM", issue: "Source assets are unmapped", detail: "These observed assets are excluded from automated execution until a human confirms their mapping.", scope: plural(unmappedSources, "source asset"), status: "EXCLUDED", lastSeen: display(data.analysis.generated_at ?? data.generatedAt, "Not available"), action: "Review coverage", href: "/map-flows" });
    }
    return rows;
  }, [data, hasActiveScope, latestRun, failedChecks, erroredChecks, runExecuted, openIncidents, integrations, reviewRequired, unmappedSources]);

  const filteredAttention = attentionRows.filter((row) => attentionFilter === "ALL" || row.status === attentionFilter || (attentionFilter === "REVIEW" && row.status === "EXCLUDED"));
  const attentionPageCount = Math.max(1, Math.ceil(filteredAttention.length / ATTENTION_PAGE_SIZE));
  const visibleAttentionRows = filteredAttention.slice((attentionPage - 1) * ATTENTION_PAGE_SIZE, attentionPage * ATTENTION_PAGE_SIZE);
  useEffect(() => { setAttentionPage(1); }, [attentionFilter]);
  useEffect(() => { if (attentionPage > attentionPageCount) setAttentionPage(attentionPageCount); }, [attentionPage, attentionPageCount]);
  const topResults = Array.isArray(latestRun?.results) ? latestRun.results as Payload[] : [];
  const resultPageCount = Math.max(1, Math.ceil(topResults.length / RESULT_PAGE_SIZE));
  const visibleResultRows = topResults.slice((resultPage - 1) * RESULT_PAGE_SIZE, resultPage * RESULT_PAGE_SIZE);
  useEffect(() => { setResultPage(1); }, [latestRun?.run_id]);
  useEffect(() => { if (resultPage > resultPageCount) setResultPage(resultPageCount); }, [resultPage, resultPageCount]);
  const topChecks = topResults.filter((item) => ["FAIL", "ERROR"].includes(display(item.status).toUpperCase())).slice(0, 3);
  const planStatus = label(data?.plan.status ?? "NOT GENERATED");

  return <DraftShell active="operations">
    <PageHeader eyebrow="AUTOMATED DATA QUALITY / OVERVIEW" title="Overview" description="Current scoped state plus clearly labelled persisted history for the active project." status={<span className={styles.draftBadge}>{data ? `${data.workspace.name} · ${data.workspace.environment} · ${refreshState === "LIVE" ? "live checked" : refreshState === "REFRESHING" ? "refreshing live state" : refreshState === "ERROR" ? "live refresh failed" : "saved snapshot"} · ${new Date(data.generatedAt).toLocaleTimeString()}` : "LOADING"}</span>} actions={<button className={styles.secondary} disabled={busy} onClick={() => void loadLiveEvidence()}>{busy ? "Refreshing…" : "Refresh live evidence"}</button>} />

    {error && <ErrorState title="Operations data unavailable">{error}</ErrorState>}
    {data && !hasActiveScope && <div className={styles.infoStrip} role="status"><span>i</span><div><strong>No active source-table scope</strong><p>Current analysis, quality plans, runs, and asset records stay empty until a source table is selected. Persisted history is not presented as current state.</p><ScopedLink className={styles.tableLink} href="/register-project?phase=onboarding">Select a source table →</ScopedLink></div></div>}

    {!data ? <><section className={styles.statusCardGrid} aria-label="Operations loading"><article className={styles.statusCard}><strong className={styles.loadingBar}>Loading</strong><small>Reading current run state</small></article><article className={styles.statusCard}><strong className={styles.loadingBar}>Loading</strong><small>Checking incidents</small></article><article className={styles.statusCard}><strong className={styles.loadingBar}>Loading</strong><small>Checking connections</small></article><article className={styles.statusCard}><strong className={styles.loadingBar}>Loading</strong><small>Calculating coverage</small></article></section><section className={styles.panel}><p>Runtime refresh is running in the background. The page will remain usable while evidence is collected.</p></section></> : <>
      <section className={styles.statusCardGrid} aria-label="Actionable status">
        <article className={styles.statusCard}>
          <div className={styles.statusCardHeader}><span>Latest quality run</span><StatusBadge value={latestRun?.status ?? "NOT_RUN"} label={label(latestRun?.status ?? "NOT RUN")} /></div>
          <strong>{latestRun ? plural(runExecuted, "check") : "No persisted run"}</strong>
          <small>{latestRun ? `${failedChecks} failed · ${erroredChecks} errors · ${passedChecks} passed` : "Execution evidence will appear here after a run."}</small>
          <div className={styles.statusCardFooter}><span>{latestRun ? `Recorded ${persistedRunTime(latestRun)}` : "No historical record"}</span><ScopedLink href="/test-plan?view=execution">View persisted run →</ScopedLink></div>
        </article>
        <article className={styles.statusCard}>
          <div className={styles.statusCardHeader}><span>Open incidents</span><StatusBadge value={!hasExecutionEvidence ? "NOT_CHECKED" : openIncidents.length ? "FAILED" : "COMPLETED"} label={!hasExecutionEvidence ? "NOT CHECKED" : openIncidents.length ? "ACTION" : "CLEAR"} /></div>
          <strong>{openIncidents.length}</strong>
          <small>{!hasExecutionEvidence ? "No execution evidence has produced incidents or alerts." : openIncidents.length ? `${openAlerts.length} active alerts linked to current incidents.` : "No open incidents or active alerts."}</small>
          <div className={styles.statusCardFooter}><span>Failed-run evidence only</span><ScopedLink href="/incidents">Review incidents →</ScopedLink></div>
        </article>
        <article className={styles.statusCard}>
          <div className={styles.statusCardHeader}><span>Connection health</span><StatusBadge value={!totalConnections ? "NOT_CHECKED" : passingConnections === totalConnections ? "READY" : "UNCERTAIN"} label={connectionSummary(passingConnections, totalConnections)} /></div>
          <strong>{totalConnections ? `${passingConnections} of ${totalConnections}` : "—"}</strong>
          <small>{totalConnections ? (passingConnections === totalConnections ? "All registered adapters passed their latest check." : "One or more adapters need attention.") : "No saved connection checks are available."}</small>
          <div className={styles.statusCardFooter}><span>Last check: {formatDate(latestConnectionCheck, "Not checked")}</span><Link href="/register-project">Review connections →</Link></div>
        </article>
        <article className={styles.statusCard}>
          <div className={styles.statusCardHeader}><span>Coverage gaps</span><StatusBadge value={!analysisChecked ? "NOT_CHECKED" : unmappedSources ? "UNCERTAIN" : "COMPLETED"} label={!analysisChecked ? "NOT CHECKED" : unmappedSources ? "EXCLUDED" : "COVERED"} /></div>
          <strong>{analysisChecked ? unmappedSources : "—"}</strong>
          <small>{analysisChecked ? "Observed source assets not yet mapped to an approved target." : "Live analysis is unavailable; saved discovery remains separate."}</small>
          <div className={styles.statusCardFooter}><span>Never guessed automatically</span><ScopedLink href="/map-flows">Review coverage →</ScopedLink></div>
        </article>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <div><h2>Needs attention</h2><p>Aggregated work queues keep the page actionable without turning every failed check into a separate incident.</p></div>
          <span>{attentionRows.length} QUEUES</span>
        </header>
        <div className={styles.attentionToolbar}>
          <div className={styles.filterTabs}>{(["ALL", "BLOCKED", "REVIEW", "APPROVAL"] as AttentionFilter[]).map((filter) => <button key={filter} className={attentionFilter === filter ? styles.activeFilter : ""} onClick={() => setAttentionFilter(filter)}>{filter === "ALL" ? "All" : label(filter)}</button>)}</div>
          <span className={styles.tableMeta}>{filteredAttention.length} visible</span>
        </div>
        <div className={styles.attentionTableWrap}>
          <table className={styles.attentionTable}><thead><tr><th>Priority</th><th>Issue</th><th>Scope</th><th>Status</th><th>Last seen</th><th>Action</th></tr></thead><tbody>
            {visibleAttentionRows.length ? visibleAttentionRows.map((row) => <tr key={row.id}><td><span className={`${styles.priority} ${row.priority === "HIGH" ? styles.priorityHigh : styles.priorityMedium}`}>{row.priority}</span></td><td><strong>{row.issue}</strong><small>{row.detail}</small></td><td>{row.scope}</td><td><span className={`${styles.statusPill} ${row.status === "BLOCKED" ? styles.statusBad : row.status === "APPROVAL" ? styles.statusWarn : styles.statusNeutral}`}>{label(row.status)}</span></td><td>{row.lastSeen === "Not available" ? row.lastSeen : formatDate(row.lastSeen)}</td><td><ScopedLink className={styles.tableLink} href={row.href}>{row.action} →</ScopedLink></td></tr>) : <tr><td colSpan={6} className={styles.emptyTable}>Nothing matches this filter.</td></tr>}
          </tbody></table>
          {filteredAttention.length > ATTENTION_PAGE_SIZE && <nav className={styles.tablePagination} aria-label="Needs attention pages"><span>Page {attentionPage} of {attentionPageCount}</span><div><button disabled={attentionPage === 1} onClick={() => setAttentionPage((current) => Math.max(1, current - 1))}>Previous</button><button disabled={attentionPage === attentionPageCount} onClick={() => setAttentionPage((current) => Math.min(attentionPageCount, current + 1))}>Next</button></div></nav>}
        </div>
      </section>

      <div className={styles.operationsGrid}>
        <div className={styles.sectionStack}>
          <section className={styles.panel}>
            <header className={styles.panelHead}><div><h2>Latest quality run summary</h2><p>Execution evidence is separate from the plan: selected checks do not mean passed checks.</p></div><ScopedLink className={`${styles.secondary} ${styles.linkButton}`} href="/test-plan?view=execution">Open run history</ScopedLink></header>
            <div className={styles.runSummaryHeader}><div><span className={styles.muted}>PERSISTED PLAN REVISION {display(data.plan.revision)}</span><strong>{latestRun ? label(latestRun.status) : "NO PERSISTED RUN"}</strong><small>{latestRun ? `Recorded ${persistedRunTime(latestRun)}` : "No persisted execution evidence for the current scope"}</small></div><StatusBadge value={latestRun?.status ?? "NOT_RUN"} label={latestRun ? label(latestRun.status) : "NO PERSISTED RUN"} /></div>
            <div className={styles.runKpis}><div><span>Checks in plan</span><strong>{asNumber(planSummary.check_count)}</strong><small>{asNumber(planSummary.enabled_check_count)} enabled</small></div><div><span>Executed</span><strong>{runExecuted || "—"}</strong><small>{latestRun ? "Persisted result rows" : "Waiting for run"}</small></div><div><span>Trigger</span><strong>{label(latestRun?.trigger ?? "SCHEDULED")}</strong><small>{label(latestRun?.execution_mode ?? "DETERMINISTIC")}</small></div></div>
            <div className={styles.runBreakdown}><div><span className={styles.breakdownPass}></span><strong>{passedChecks}</strong><small>Passed</small></div><div><span className={styles.breakdownFail}></span><strong>{failedChecks}</strong><small>Failed</small></div><div><span className={styles.breakdownError}></span><strong>{erroredChecks}</strong><small>Errors</small></div></div>
            {topChecks.length ? <div className={styles.topChecks}><h3>Checks needing review</h3>{topChecks.map((item, index) => <div className={styles.topCheck} key={`${display(item.check_id)}-${index}`}><span>{label(item.status)}</span><strong>{display(item.name, "Unnamed check")}</strong><small>{display(item.category, "Quality check")} · deterministic evidence</small></div>)}</div> : latestRun ? <div className={styles.successStrip}>No failed or errored checks were reported in the latest persisted run.</div> : <div className={styles.infoStrip}><span>i</span><div><strong>NOT RUN — no execution evidence</strong><p>Incidents and investigations remain empty until an approved pipeline or quality run produces evidence.</p></div></div>}
            {latestRun && <section className={styles.resultTableSection} aria-label="Latest run results"><header><div><h3>Run results</h3><p>Paginated persisted results for this run.</p></div><span>{topResults.length} total</span></header><div className={styles.attentionTableWrap}><table className={styles.attentionTable}><thead><tr><th>Status</th><th>Check</th><th>Category</th><th>Evidence</th></tr></thead><tbody>{visibleResultRows.map((item, index) => <tr key={`${display(item.check_id)}-${index}`}><td><StatusBadge value={item.status} label={label(item.status) || "Not checked"} /></td><td><strong>{display(item.name, "Unnamed check")}</strong></td><td>{display(item.category, "Quality check")}</td><td>{display(asPayload(item.result).source ?? item.evidence_source, "Persisted result")}</td></tr>)}</tbody></table></div>{topResults.length > RESULT_PAGE_SIZE && <nav className={styles.tablePagination} aria-label="Run result pages"><span>Page {resultPage} of {resultPageCount}</span><div><button disabled={resultPage === 1} onClick={() => setResultPage((current) => Math.max(1, current - 1))}>Previous</button><button disabled={resultPage === resultPageCount} onClick={() => setResultPage((current) => Math.min(resultPageCount, current + 1))}>Next</button></div></nav>}</section>}
          </section>

          <section className={styles.panel}>
            <header className={styles.panelHead}><div><h2>Workflow lifecycle</h2><p>Each phase is a reviewable surface; the Operations page is the control-plane summary.</p></div></header>
            <div className={styles.nodeFlow}><Link className={styles.graphNode} href="/register-project"><span>1–3</span><strong>Configure & discover</strong><small>Profiles, inventories, and connector-specific filters</small></Link><Link className={styles.graphNode} href="/map-flows"><span>4–5</span><strong>Analyze & map</strong><small>{asNumber(analysisSummary.exceptions)} unresolved exceptions</small></Link><Link className={styles.graphNode} href="/test-plan?view=contracts"><span>6</span><strong>Quality rules</strong><small>{planStatus} · {reviewRequired} need confirmation</small></Link><Link className={styles.graphNode} href="/reconciliation"><span>7</span><strong>Reconcile</strong><small>{hasExecutionEvidence ? "Compare post-run tables" : "Baseline available before a run"}</small></Link><Link className={styles.graphNode} href="/test-plan?view=execution"><span>8</span><strong>Execute & verify</strong><small>{latestRuns.length} persisted runs</small></Link><Link className={styles.graphNode} href="/incidents"><span>9</span><strong>Incidents</strong><small>{openIncidents.length} open incidents</small></Link></div>
          </section>
        </div>

        <aside className={styles.sideStack}>
          <section className={styles.panel}>
            <header className={styles.panelHead}><div><h2>Coverage summary</h2><p>Proposed placement is a review aid, not verified lineage.</p></div><Link className={`${styles.secondary} ${styles.linkButton}`} href="/map-flows">Review coverage</Link></header>
            <div className={styles.coverageStats}><div><strong>{discoveredAssets || "—"}</strong><span>Discovered assets</span></div><div><strong>{analysisChecked ? mappedAssets || "—" : "—"}</strong><span>Mapped</span></div><div><strong>{analysisChecked ? unmappedSources || "—" : "—"}</strong><span>Unmapped sources</span></div></div>
            <div className={styles.coverageTrack}><span style={{ width: `${coveragePercent}%` }}></span></div><div className={styles.coverageCaption}><span>{analysisChecked ? `${coveragePercent}% mapped` : "Mapping not checked"}</span><span>{!analysisChecked ? "Live analysis unavailable" : unmappedSources ? `${unmappedSources} excluded from execution` : "No source gaps"}</span></div>
          </section>

          <section className={styles.panel}>
            <header className={styles.panelHead}><div><h2>Connection health</h2><p>Adapter checks are independent from the canonical console at {consoleLocation}. Airflow uses its configured runtime endpoint; this UI does not redirect to it.</p></div><div className={styles.panelActions}><StatusBadge value={!totalConnections ? "NOT_CHECKED" : passingConnections === totalConnections ? "READY" : "UNCERTAIN"} label={connectionSummary(passingConnections, totalConnections)} /><button className={styles.secondary} disabled={busy} onClick={() => void loadLiveEvidence()}>{busy ? "Syncing…" : "Sync connections"}</button></div></header>
            <div className={styles.connectionList}>{integrations.map(([name, value]) => { const state = integrationConnectionState(value); const count = value.object_count ?? value.registered_dag_count ?? (asPayload(value.resource_counts).model) ?? (Array.isArray(value.models) ? value.models.length : undefined); const freshness = label(value.freshness ?? "NOT REFRESHED"); return <div className={styles.connectionRow} key={name}><span className={`${styles.connectionDot} ${state === "PASSING" ? styles.dotGood : state === "ATTENTION" ? styles.dotBad : styles.dotUnknown}`}></span><div><strong>{name.toUpperCase()}</strong><small>{state === "PASSING" ? `${count === undefined ? "Available" : `${count} observed assets`}` : display(value.reason ?? value.runtime_error ?? value.detail, "Adapter needs review")} · {freshness.toLowerCase()}</small>{name.toLowerCase() === "airflow" && <small>Airflow endpoint: {integrationEndpoint(value)}</small>}</div><StatusBadge value={state === "PASSING" ? "READY" : state === "ATTENTION" ? "FAILED" : "NOT_CHECKED"} label={label(state)} /></div>; })}</div>
            <Link className={styles.tableLink} href="/register-project">Open connection manager →</Link>
          </section>

        </aside>
      </div>
    </>}
  </DraftShell>;
}
