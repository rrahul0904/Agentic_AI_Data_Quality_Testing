"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import DraftShell from "../DraftShell";
import styles from "../workflow.module.css";
import { ErrorState, PageHeader, StatusBadge } from "../components/ui";
import ScopedLink from "../components/ScopedLink";
import { scopedApiUrl } from "../../lib/client-workspace";
import { currentWorkspaceParams } from "../../lib/client-workspace";
import { monitoringStatusLabel as statusLabel, safeDisplayError as errorMessage } from "../../lib/ui-contracts";
import { clearMonitoringSelection, monitoringSelectedRunKey, monitoringScopeKey, readMonitoringFilters, rememberedMonitoringRun, type MonitoringScope } from "../../lib/monitoring-state";
import local from "./monitoring.module.css";

type Job = Record<string, unknown>;
type Feed = { items?: Job[]; total?: number; page?: number; page_size?: number; has_next?: boolean; status?: string; error?: unknown; workspace?: { projectId?: string; environment?: string; scopeLocked?: boolean } };
type RecoveryAction = { action: string; label: string; impact: string; required_role?: string; allowed?: boolean; disabled_reason?: string | null };
type RecoveryItem = { work?: Job; run?: Job; plan?: Job; recovery_actions?: RecoveryAction[] };
type RecoveryFeed = { items?: RecoveryItem[]; error?: unknown };
type RunDetail = Job & { error?: unknown; load_error?: unknown };
function scopeFromRecord(value: Job): MonitoringScope | null {
  const plan = value.plan && typeof value.plan === "object" ? value.plan as Job : {};
  const projectId = rawId(value.project_id ?? plan.project_id);
  const environment = rawId(value.environment ?? plan.environment);
  return projectId && environment ? { projectId, environment } : null;
}

function text(value: unknown, fallback = "—"): string { return value === null || value === undefined || value === "" ? fallback : String(value).replaceAll("_", " "); }
function date(value: unknown): string { if (!value) return "Not observed"; const parsed = new Date(String(value)); return Number.isNaN(parsed.getTime()) ? "Not observed" : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); }
function duration(value: unknown): string { return value == null ? "—" : `${text(value)}s`; }
function rawId(value: unknown): string { return typeof value === "string" ? value : ""; }
function outcomeStatus(item: Job, bucket: string): unknown {
  const outcomes = item.outcomes;
  if (!outcomes || typeof outcomes !== "object") return undefined;
  const value = (outcomes as Record<string, unknown>)[bucket];
  return value && typeof value === "object" ? (value as Record<string, unknown>).status : undefined;
}
function shortJobName(job: Job): string {
  const plan = job.plan && typeof job.plan === "object" ? job.plan as Job : {};
  const step = job.current_step_details && typeof job.current_step_details === "object" ? job.current_step_details as Job : {};
  const candidate = text(step.asset ?? job.asset ?? plan.intent ?? job.run_id, "Unnamed job");
  return candidate.replace(/^Please run /i, "").replace(/^Run /i, "").replace(/\s+/g, " ").slice(0, 72);
}

export default function MonitoringPage() {
  const [feed, setFeed] = useState<Feed>({});
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [status, setStatus] = useState("");
  const [technology, setTechnology] = useState("");
  const [asset, setAsset] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [projectId, setProjectId] = useState("");
  const [environment, setEnvironment] = useState("");
  const [page, setPage] = useState(1);
  const [restoredRunId, setRestoredRunId] = useState("");
  const [busy, setBusy] = useState(false);
  const [detailBusy, setDetailBusy] = useState(false);
  const [recovery, setRecovery] = useState<RecoveryFeed>({});
  const [expandedSequence, setExpandedSequence] = useState<string | null>(null);
  const [scopeReady, setScopeReady] = useState(false);
  const [scopeError, setScopeError] = useState("");
  const detailOpener = useRef<HTMLElement | null>(null);
  const restoredScopeRef = useRef("");

  useEffect(() => {
    let active = true;
    const params = currentWorkspaceParams();
    const requested = { projectId: params.get("project_id") || "", environment: params.get("environment") || "" };
    void fetch(scopedApiUrl("/api/workspace"), { cache: "no-store", signal: AbortSignal.timeout(5000) })
      .then((response) => response.ok ? response.json() as Promise<{ projectId?: string; environment?: string }> : Promise.reject(new Error("Current project scope is unavailable")))
      .then((workspace) => {
        if (!active) return;
        const scope = { projectId: requested.projectId || workspace.projectId || "", environment: requested.environment || workspace.environment || "" };
        if (!scope.projectId || !scope.environment) throw new Error("Select a project and environment before viewing monitoring history");
        const persisted = readMonitoringFilters(window.localStorage, scope);
        setProjectId(scope.projectId); setEnvironment(scope.environment);
        setStatus(persisted.status); setTechnology(persisted.technology); setAsset(persisted.asset);
        setSince(persisted.since); setUntil(persisted.until); setPage(persisted.page);
        setRestoredRunId(rememberedMonitoringRun(window.localStorage, scope));
        setScopeError(""); setScopeReady(true);
      })
      .catch((error) => { if (active) { setScopeError(error instanceof Error ? error.message : "Current project scope is unavailable"); setScopeReady(false); } });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!scopeReady || !projectId || !environment) return;
    try { window.localStorage.setItem(`ade-monitoring-filters:${monitoringScopeKey({ projectId, environment })}`, JSON.stringify({ status, technology, asset, since, until, page })); } catch { /* Storage is optional. */ }
  }, [scopeReady, projectId, environment, status, technology, asset, since, until, page]);

  const changeScope = (nextProjectId: string, nextEnvironment: string) => {
    const previous = { projectId, environment };
    if (previous.projectId === nextProjectId && previous.environment === nextEnvironment) return;
    clearMonitoringSelection(window.localStorage, previous);
    restoredScopeRef.current = "";
    setDetail(null); setRestoredRunId(""); setExpandedSequence(null); setFeed({}); setRecovery({}); setPage(1);
    setProjectId(nextProjectId); setEnvironment(nextEnvironment);
    const next = new URL(window.location.href);
    if (nextProjectId) next.searchParams.set("project_id", nextProjectId); else next.searchParams.delete("project_id");
    if (nextEnvironment) next.searchParams.set("environment", nextEnvironment); else next.searchParams.delete("environment");
    window.history.replaceState({}, "", next.toString());
  };

  async function selectRun(runId: string) {
    if (!runId) return;
    setDetailBusy(true);
    try {
      const query = new URLSearchParams({
        project_id: projectId,
        environment,
      });
      const response = await fetch(scopedApiUrl(`/api/monitoring/runs/${encodeURIComponent(runId)}?${query}`), { cache: "no-store", signal: AbortSignal.timeout(5000) });
      const value = await response.json() as RunDetail;
      if (!response.ok) throw new Error(errorMessage(value.error ?? value, "The selected run is unavailable"));
      if (!value.run_id && (value.error !== undefined || value.message !== undefined || value.error_type !== undefined)) {
        throw new Error(errorMessage(value.error ?? value, "The selected run is unavailable"));
      } else {
        // A persisted failed run may legitimately contain an `error` outcome. Keep
        // the run detail available so its execution, verification, and evidence
        // states remain inspectable instead of treating the outcome as a load error.
        const recordScope = scopeFromRecord(value);
        if (recordScope && (recordScope.projectId !== projectId || recordScope.environment !== environment)) {
          throw new Error("The selected run belongs to a different project or environment");
        }
        setDetail(value);
        try { window.localStorage.setItem(monitoringSelectedRunKey({ projectId, environment }), runId); } catch { /* Storage is optional. */ }
      }
    } catch (error) {
      clearMonitoringSelection(window.localStorage, { projectId, environment });
      setRestoredRunId("");
      setDetail({ run_id: runId, load_error: error instanceof Error ? error.message : "The selected run is unavailable" });
    }
    finally { setDetailBusy(false); }
  }

  async function runRecovery(runId: string, operation: string) {
    if (!runId) return;
    setBusy(true);
    try {
      const response = await fetch(scopedApiUrl(`/api/monitoring/runs/${encodeURIComponent(runId)}/${encodeURIComponent(operation)}`), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      const value = await response.json() as { error?: unknown };
      if (!response.ok) throw new Error(errorMessage(value.error, "Recovery request was rejected"));
      await load(page);
      await selectRun(runId);
    } catch (error) {
      setFeed((current) => ({ ...current, error: error instanceof Error ? error.message : "Recovery request failed" }));
    } finally { setBusy(false); }
  }

  const load = async (requestedPage = page) => {
    setBusy(true);
    try {
      const params = new URLSearchParams({ page: String(requestedPage), page_size: "25", project_id: projectId, environment });
      if (status) params.set("status", status);
      if (technology) params.set("technology", technology);
      if (asset) params.set("asset", asset);
      if (since) params.set("since", new Date(since).toISOString());
      if (until) params.set("until", new Date(until).toISOString());
      const [response, recoveryResponse] = await Promise.all([
        fetch(scopedApiUrl(`/api/monitoring?${params}`), { cache: "no-store", signal: AbortSignal.timeout(5000) }),
        fetch(scopedApiUrl(`/api/monitoring/recovery?project_id=${encodeURIComponent(projectId)}&environment=${encodeURIComponent(environment)}`), { cache: "no-store", signal: AbortSignal.timeout(5000) }).catch(() => null),
      ]);
      const value = await response.json() as Feed;
      const recoveryValue = recoveryResponse ? await recoveryResponse.json() as RecoveryFeed : { error: "Recovery queue is temporarily unavailable" };
      if (!response.ok) throw new Error(errorMessage(value.error, "Monitoring is unavailable"));
      setRecovery(recoveryResponse?.ok ? recoveryValue : { error: errorMessage(recoveryValue.error, "Recovery queue is unavailable") });
      if (value.workspace?.projectId) setProjectId(value.workspace.projectId);
      if (value.workspace?.environment) setEnvironment(value.workspace.environment);
      setFeed(value);
    } catch (error) { setFeed({ error: error instanceof Error ? error.message : "Monitoring is unavailable" }); }
    finally { setBusy(false); }
  };

  useEffect(() => { if (scopeReady && projectId && environment) void load(page); }, [scopeReady, projectId, environment]);
  useEffect(() => {
    const scope = { projectId, environment };
    const marker = `${monitoringScopeKey(scope)}:${restoredRunId}`;
    if (!scopeReady || !restoredRunId || !feed.workspace?.projectId || restoredScopeRef.current === marker) return;
    restoredScopeRef.current = marker;
    void selectRun(restoredRunId);
  }, [scopeReady, projectId, environment, restoredRunId, feed.workspace?.projectId]);
  const jobs = Array.isArray(feed.items) ? feed.items : [];
  const groups = useMemo(() => {
    const grouped = new Map<string, Job[]>();
    for (const job of jobs) { const key = text(job.sequence_id ?? (job.plan as Job | undefined)?.plan_id, "unassigned"); grouped.set(key, [...(grouped.get(key) ?? []), job]); }
    return Array.from(grouped.entries());
  }, [jobs]);

  const closeDetails = () => {
    setDetail(null); setRestoredRunId("");
    clearMonitoringSelection(window.localStorage, { projectId, environment });
    window.setTimeout(() => detailOpener.current?.focus(), 0);
  };

  return <DraftShell active="monitoring">
    <PageHeader eyebrow="AUTOMATED DATA QUALITY / MONITORING" title="Monitoring" description="Review persisted job history for the active project and environment. Current adapter state is not inferred from an old run." status={<span className={styles.draftBadge}>{scopeReady ? `${feed.total ?? 0} PERSISTED JOBS` : "SCOPE UNAVAILABLE"}</span>} actions={<button className={styles.secondary} disabled={busy || !scopeReady} aria-busy={busy} onClick={() => void load()}>{busy ? "Refreshing…" : "Refresh"}</button>} />
    <section className={styles.panel}>
      <header className={styles.panelHead}><div><h2>Job monitor</h2><p>Execution success and data-quality success are separate outcomes. Reading this page never starts a job.</p></div><ScopedLink className={`${styles.secondary} ${styles.linkButton}`} href="/actions">Create run plan</ScopedLink></header>
      {scopeError && <ErrorState title="Current project scope unavailable">{scopeError}</ErrorState>}
      {!scopeReady && !scopeError && <div className={styles.infoStrip} role="status"><span>i</span><div><strong>Loading current project scope</strong><p>Monitoring history will appear after the browser context is confirmed.</p></div></div>}
      <div className={styles.attentionToolbar}><label className={styles.field}>Project<input value={projectId} disabled={!scopeReady || Boolean(feed.workspace?.scopeLocked)} onChange={(event) => changeScope(event.target.value, environment)} /></label><label className={styles.field}>Environment<select value={environment} disabled={!scopeReady || Boolean(feed.workspace?.scopeLocked)} onChange={(event) => changeScope(projectId, event.target.value)}><option value="">Select environment</option><option value="development">Development</option><option value="production">Production</option><option value="staging">Staging</option></select></label><label className={styles.field}>Status<select value={status} disabled={!scopeReady} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="">All statuses</option><option value="QUEUED">Queued</option><option value="SUBMITTING">Submitting</option><option value="MONITORING">Monitoring</option><option value="VERIFYING">Verifying</option><option value="COMPLETED">Completed</option><option value="FAILED">Failed</option><option value="UNCERTAIN">Uncertain</option><option value="BLOCKED">Blocked</option></select></label><label className={styles.field}>Technology<input value={technology} disabled={!scopeReady} placeholder="Airflow, dbt, Snowflake" onChange={(event) => { setTechnology(event.target.value); setPage(1); }} /></label><label className={styles.field}>Asset<input value={asset} disabled={!scopeReady} placeholder="table, DAG, model" onChange={(event) => { setAsset(event.target.value); setPage(1); }} /></label><label className={styles.field}>From<input type="datetime-local" value={since} disabled={!scopeReady} onChange={(event) => { setSince(event.target.value); setPage(1); }} /></label><label className={styles.field}>To<input type="datetime-local" value={until} disabled={!scopeReady} onChange={(event) => { setUntil(event.target.value); setPage(1); }} /></label><button className={styles.primary} disabled={busy || !scopeReady} onClick={() => void load(1)}>Apply filters</button></div>
      <div className={styles.stateLegend} aria-label="Monitoring outcome legend"><span className={styles.statusGood}><i />Execution and verification passed</span><span className={styles.statusWarn}><i />Waiting, queued, or awaiting continuation</span><span className={styles.statusBad}><i />Failed, blocked, or outcome unknown</span></div>
      {Boolean(feed.error) && <ErrorState title="Monitoring unavailable">{errorMessage(feed.error, "Monitoring is unavailable")}</ErrorState>}
      {Array.isArray(recovery.items) && recovery.items.length > 0 && <section className={styles.panel} aria-label="Operator recovery queue"><header className={styles.panelHead}><div><span className={styles.eyebrow}>OPERATOR ACTION</span><h2>Recovery queue</h2><p>Blocked work stays visible. Each action states whether it reads state or can continue an approved step.</p></div><span className={`${styles.statusPill} ${styles.statusBad}`}>{recovery.items.length} NEED ATTENTION</span></header><div className={styles.summaryList}>{recovery.items.map((item) => { const work = item.work ?? {}; const run = item.run ?? {}; const plan = item.plan ?? {}; const runId = rawId(work.run_id ?? run.run_id); const actions = item.recovery_actions ?? []; return <div className={styles.recoveryRow} key={runId || String(work.work_id)}><div><strong>{text(plan.intent, runId)}</strong><small>{statusLabel(work.state)} · attempt {text(work.attempt, "0")} of {text(work.max_attempts, "—")} · {text(work.last_error, "No recovery reason recorded")}</small></div><div className={styles.recoveryActions}><ScopedLink className={styles.secondary} href={`/actions?run_id=${encodeURIComponent(runId)}#execution-monitor`}>Open run</ScopedLink>{actions.map((action) => <button className={styles.secondary} key={action.action} title={action.allowed ? action.impact : action.disabled_reason ?? "Permission required"} disabled={!action.allowed || busy} onClick={() => void runRecovery(runId, action.action)}>{action.label}</button>)}</div></div>; })}</div></section>}
      {busy && !feed.error && !jobs.length && <div className={styles.infoStrip} role="status"><span>i</span><div><strong>Loading job history</strong><p>Keeping the current project and environment scope while the latest page is retrieved.</p></div></div>}
      {!busy && !feed.error && scopeReady && !jobs.length && <div className={styles.infoStrip}><span>i</span><div><strong>{feed.status === "NO_MATCHING_ASSET_FILTER" ? "No persisted jobs match this filter" : "No persisted jobs for this project and environment"}</strong><p>{feed.status === "NO_MATCHING_ASSET_FILTER" ? "Clear the asset filter to review the rest of this project history." : "No historical execution record is available yet. Create an approved run plan when you are ready."}</p><ScopedLink className={styles.tableLink} href="/actions">Create run plan →</ScopedLink></div></div>}
      <div className={styles.sectionStack}>{groups.map(([sequence, group]) => <section className={styles.panel} key={sequence}><header className={styles.panelHead}><div><h3>{sequence === "unassigned" ? "Individual jobs" : "Selected sequence"}</h3><p>{sequence === "unassigned" ? `${group.length} independent job${group.length === 1 ? "" : "s"}` : `${group.length} ordered step${group.length === 1 ? "" : "s"} · expand to inspect dependencies`}</p></div><div className={styles.monitorGroupActions}><StatusBadge value={group[0].execution_status} />{sequence !== "unassigned" && <button className={styles.secondary} onClick={() => setExpandedSequence((current) => current === sequence ? null : sequence)} aria-expanded={expandedSequence === sequence}>{expandedSequence === sequence ? "Hide steps" : "Show steps"}</button>}</div></header>{expandedSequence === sequence && sequence !== "unassigned" && <div className={styles.sequenceSummary} aria-label={`Steps in ${sequence}`}>{group.map((job, index) => { const step = job.current_step_details && typeof job.current_step_details === "object" ? job.current_step_details as Job : {}; const dependencies = Array.isArray(job.depends_on) ? job.depends_on.map(String).join(", ") : "none recorded"; return <div className={styles.sequenceSummaryRow} key={rawId(job.run_id) || `${sequence}-${index}`}><b>{text(step.sequence ?? job.sequence ?? index + 1)}</b><div><strong>{shortJobName(job)}</strong><small>Depends on: {dependencies}</small></div><div><StatusBadge value={job.execution_status} /><StatusBadge value={job.execution_verification_status ?? job.verification_status} label={statusLabel(job.execution_verification_status ?? job.verification_status, "Not checked")} /></div></div>; })}</div>}<div className={styles.attentionTableWrap}><table className={styles.attentionTable}><thead><tr><th>Job / asset</th><th>Execution</th><th>Verification</th><th>Last checked</th><th> </th></tr></thead><tbody>{group.map((job) => { const runId = rawId(job.run_id); return <tr key={runId}><td><strong>{shortJobName(job)}</strong><small>{runId || "Run identifier unavailable"}</small></td><td><StatusBadge value={job.execution_status} /></td><td><StatusBadge value={job.execution_verification_status ?? job.verification_status} label={statusLabel(job.execution_verification_status ?? job.verification_status, "Not checked")} /></td><td>{date(job.last_observation)}{job.stale ? <small className={styles.warningText}>Refresh recommended</small> : null}</td><td><button className={styles.secondary} disabled={!runId} aria-label={`View details for ${runId || "selected job"}`} onClick={(event) => { detailOpener.current = event.currentTarget; void selectRun(runId); }}>View details</button></td></tr>; })}</tbody></table></div></section>)}</div>
      <nav className={styles.tablePagination} aria-label="Monitoring pages"><span>Project {projectId} · {environment} · Page {feed.page ?? page} · {feed.total ?? 0} total</span><div><button disabled={busy || page <= 1} onClick={() => { const next = page - 1; setPage(next); void load(next); }}>Previous</button><button disabled={busy || !feed.has_next} onClick={() => { const next = page + 1; setPage(next); void load(next); }}>Next</button></div></nav>
    </section>
    {detail && <RunDetails detail={detail} busy={detailBusy} projectId={projectId} environment={environment} onRecovery={(operation) => void runRecovery(detailRunId(detail), operation)} onClear={closeDetails} />}
  </DraftShell>;
}

function detailRunId(detail: RunDetail): string { return rawId(detail.run_id); }

function RunDetails({ detail, busy, projectId, environment, onRecovery, onClear }: { detail: RunDetail; busy: boolean; projectId: string; environment: string; onRecovery: (operation: string) => void; onClear: () => void }) {
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClear(); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClear]);
  const shell = (children: ReactNode) => <div className={local.drawerBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClear(); }}><aside className={local.runDrawer} id="selected-run" role="dialog" aria-modal="true" aria-labelledby="selected-run-title">{children}</aside></div>;
  if (detail.load_error) return shell(<><header className={styles.panelHead}><div><span className={styles.eyebrow}>SELECTED JOB</span><h2 id="selected-run-title">Unable to load selected run</h2><p><code>{rawId(detail.run_id) || "Unavailable"}</code></p></div><button className={styles.secondary} ref={closeButton} onClick={onClear}>Close</button></header><ErrorState title="Run details unavailable"><>{errorMessage(detail.load_error, "The selected run could not be loaded for this project and environment.")} The remembered run was not replaced with another run. Close this drawer and select a persisted run from the list.</></ErrorState></>);
  const plan = detail.plan && typeof detail.plan === "object" ? detail.plan as Job : {};
  const steps = Array.isArray(detail.steps) ? detail.steps as Job[] : [];
  const attempts = Array.isArray(detail.attempt_history) ? detail.attempt_history as Job[] : [];
  const dependencies: Job[] = Array.isArray(detail.dependencies) ? detail.dependencies as Job[] : Array.isArray(plan.steps) ? (plan.steps as Job[]).map((step) => ({ sequence: step.sequence, asset: step.asset, status: "PENDING" })) : [];
  const identifiers = Array.isArray(detail.external_identifiers) ? detail.external_identifiers as Job[] : [];
  const detailRunId = rawId(detail.run_id);
  const exactEvidence = detailRunId ? `/actions?project_id=${encodeURIComponent(projectId)}&environment=${encodeURIComponent(environment)}&run_id=${encodeURIComponent(detailRunId)}#execution-monitor` : "#selected-run";
  const hasAttention = Boolean(detail.uncertainty || detail.stale);
  const uncertaintyMessage = typeof detail.uncertainty === "string" ? detail.uncertainty : detail.stale ? "The last external observation is stale." : "Uncertainty was recorded for this job.";
  const recoveryActions = Array.isArray(detail.recovery_actions) ? detail.recovery_actions as Job[] : [];
  return shell(<><header className={styles.panelHead}><div><span className={styles.eyebrow}>SELECTED JOB</span><h2 id="selected-run-title">{text(plan.intent, detailRunId)}</h2><p><code>{detailRunId || "Unavailable"}</code> · {date(detail.started_at)}</p></div><div className={local.drawerHeaderActions}><StatusBadge value={detail.state} />{busy && <small>Refreshing details…</small>}<button className={styles.secondary} ref={closeButton} onClick={onClear}>Close</button></div></header><div className={styles.summaryGrid}><div><small>Project</small><strong>{text(plan.project_id, projectId)}</strong></div><div><small>Environment</small><strong>{text(plan.environment, environment)}</strong></div><div><small>Execution outcome</small><strong>{statusLabel(detail.execution_status ?? detail.state)}</strong></div><div><small>Execution verification</small><strong>{statusLabel(detail.execution_verification_status ?? detail.verification_status, "Not checked")}</strong></div><div><small>Data-quality outcome</small><strong>{statusLabel(detail.data_quality_status, "Not checked")}</strong></div><div><small>Evidence availability</small><strong>{statusLabel(detail.evidence_status, "Not checked")}</strong></div></div>{hasAttention && <div className={styles.infoStrip}><strong>Status needs attention</strong><p>{uncertaintyMessage}</p></div>}{recoveryActions.length > 0 && <section className={styles.recoveryCallout}><h3>Recovery actions</h3><p>These actions are scoped to this run. Reconcile reads external state; continue only advances approved work.</p><div className={styles.recoveryActions}>{recoveryActions.map((action) => <button className={styles.secondary} key={String(action.action)} disabled={action.allowed === false || busy} title={String(action.allowed === false ? action.disabled_reason ?? "Permission required" : action.impact ?? "Scoped recovery action")} onClick={() => onRecovery(String(action.action))}>{String(action.label ?? action.action)}</button>)}</div></section>}<div className={styles.sectionStack}><section><h3>Lifecycle and dependencies</h3><div className={styles.summaryList}>{dependencies.map((item) => <div className={styles.summaryRow} key={String(item.sequence)}><span>{String(item.sequence)} · {text(item.asset)}<small>{text(item.kind)} · depends on {Array.isArray(item.depends_on) && item.depends_on.length ? item.depends_on.map((dependency) => String(dependency)).join(", ") : "none"}</small></span><StatusBadge value={item.status} /></div>)}</div></section><section><h3>External execution identifiers</h3><div className={styles.summaryList}>{identifiers.length ? identifiers.map((item, index) => <div className={styles.summaryRow} key={`${String(item.value)}-${index}`}><span>{text(item.technology)} · {text(item.kind)}<small><code>{String(item.value)}</code> · step {String(item.step_sequence ?? "—")}</small></span>{typeof item.url === "string" ? <a href={item.url} target="_blank" rel="noreferrer">Open external run</a> : <StatusBadge value="VERIFIED" label="Observed" />}</div>) : <div className={styles.summaryRow}><span>No external identifier persisted yet</span><strong>—</strong></div>}</div></section><section><h3>Attempt history</h3><div className={styles.summaryList}>{attempts.length ? attempts.map((item) => <div className={styles.summaryRow} key={String(item.attempt_id)}><span>Attempt {String(item.attempt)} · {text(item.worker_id)}<small>Claimed {date(item.claimed_at)} · released {date(item.released_at)}{item.error ? ` · ${text(item.error)}` : ""}</small></span><StatusBadge value={item.state} /></div>) : <div className={styles.summaryRow}><span>No worker attempts recorded</span><strong>—</strong></div>}</div></section><section><h3>Step evidence</h3><div className={styles.summaryList}>{steps.map((item) => <div className={styles.summaryRow} key={String((item.step as Job)?.sequence)}><span>{text((item.step as Job)?.asset)}<small>Execution: {statusLabel(outcomeStatus(item, "execution") ?? (item.execution as Job)?.status)} · Verification: {statusLabel(outcomeStatus(item, "execution_verification") ?? (item.verification as Job)?.status, "Not checked")} · Data quality: {statusLabel(outcomeStatus(item, "data_quality"), "Not checked")}</small></span><Link href={exactEvidence}>Open this run&apos;s evidence</Link></div>)}</div></section></div></>);
}
