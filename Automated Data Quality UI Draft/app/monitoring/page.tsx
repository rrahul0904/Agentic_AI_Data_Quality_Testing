"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import DraftShell from "../DraftShell";
import styles from "../workflow.module.css";
import { ErrorState, PageHeader, StatusBadge } from "../components/ui";
import ScopedLink from "../components/ScopedLink";
import { scopedApiUrl } from "../../lib/client-workspace";
import { currentWorkspaceParams } from "../../lib/client-workspace";
import { monitoringStatusLabel as statusLabel, safeDisplayError as errorMessage } from "../../lib/ui-contracts";

type Job = Record<string, unknown>;
type Feed = { items?: Job[]; total?: number; page?: number; page_size?: number; has_next?: boolean; status?: string; error?: unknown; workspace?: { projectId?: string; environment?: string; scopeLocked?: boolean } };
type RecoveryAction = { action: string; label: string; impact: string; required_role?: string; allowed?: boolean; disabled_reason?: string | null };
type RecoveryItem = { work?: Job; run?: Job; plan?: Job; recovery_actions?: RecoveryAction[] };
type RecoveryFeed = { items?: RecoveryItem[]; error?: unknown };
type RunDetail = Job & { error?: unknown; load_error?: unknown };

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

  useEffect(() => {
    const params = currentWorkspaceParams();
    const saved = window.localStorage.getItem("ade-monitoring-filters");
    let persisted: Record<string, string> = {};
    if (saved) {
      try { persisted = JSON.parse(saved) as Record<string, string>; } catch { window.localStorage.removeItem("ade-monitoring-filters"); }
    }
    setProjectId(params.get("project_id") || persisted.projectId || "data-quality-testing-beta");
    setEnvironment(params.get("environment") || persisted.environment || "development");
    setStatus(persisted.status || ""); setTechnology(persisted.technology || ""); setAsset(persisted.asset || "");
    setSince(persisted.since || ""); setUntil(persisted.until || ""); setPage(Number(persisted.page || 1));
    const selected = window.localStorage.getItem(`ade-monitoring-selected-run:${params.get("project_id") || persisted.projectId || "data-quality-testing-beta"}:${params.get("environment") || persisted.environment || "development"}`);
    if (selected) setRestoredRunId(selected);
  }, []);

  useEffect(() => {
    if (!projectId && !environment) return;
    window.localStorage.setItem("ade-monitoring-filters", JSON.stringify({ projectId, environment, status, technology, asset, since, until, page }));
  }, [projectId, environment, status, technology, asset, since, until, page]);

  async function selectRun(runId: string) {
    if (!runId) return;
    setDetailBusy(true);
    window.localStorage.setItem(`ade-monitoring-selected-run:${projectId}:${environment}`, runId);
    try {
      const workspace = currentWorkspaceParams();
      const query = new URLSearchParams({
        project_id: projectId || workspace.get("project_id") || "data-quality-testing-beta",
        environment: environment || workspace.get("environment") || "development",
      });
      const response = await fetch(scopedApiUrl(`/api/monitoring/runs/${encodeURIComponent(runId)}?${query}`), { cache: "no-store", signal: AbortSignal.timeout(5000) });
      const value = await response.json() as RunDetail;
      if (!response.ok) throw new Error(errorMessage(value.error ?? value, "The selected run is unavailable"));
      if (!value.run_id && (value.error !== undefined || value.message !== undefined || value.error_type !== undefined)) {
        setDetail({ run_id: runId, load_error: errorMessage(value.error ?? value, "The selected run is unavailable") });
      } else {
        // A persisted failed run may legitimately contain an `error` outcome. Keep
        // the run detail available so its execution, verification, and evidence
        // states remain inspectable instead of treating the outcome as a load error.
        setDetail(value);
      }
    } catch (error) { setDetail({ run_id: runId, load_error: error instanceof Error ? error.message : "The selected run is unavailable" }); }
    finally { setDetailBusy(false); }
  }

  async function runRecovery(runId: string, operation: string) {
    if (!runId) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/monitoring/runs/${encodeURIComponent(runId)}/${encodeURIComponent(operation)}`, {
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

  useEffect(() => { if (projectId && environment) void load(page); }, [projectId, environment]);
  useEffect(() => { if (projectId && environment && restoredRunId) void selectRun(restoredRunId); }, [projectId, environment, restoredRunId]);
  const jobs = Array.isArray(feed.items) ? feed.items : [];
  const groups = useMemo(() => {
    const grouped = new Map<string, Job[]>();
    for (const job of jobs) { const key = text(job.sequence_id ?? (job.plan as Job | undefined)?.plan_id, "unassigned"); grouped.set(key, [...(grouped.get(key) ?? []), job]); }
    return Array.from(grouped.entries());
  }, [jobs]);

  return <DraftShell active="monitoring">
    <PageHeader eyebrow="AUTOMATED DATA QUALITY / MONITORING" title="Monitoring" description="Follow each approved job from submission through execution and data-quality verification." status={<span className={styles.draftBadge}>{feed.total ?? 0} JOBS</span>} actions={<button className={styles.secondary} disabled={busy} aria-busy={busy} onClick={() => void load()}>{busy ? "Refreshing…" : "Refresh"}</button>} />
    <section className={styles.panel}>
      <header className={styles.panelHead}><div><h2>Job monitor</h2><p>Execution success and data-quality success are separate outcomes. Reading this page never starts a job.</p></div><ScopedLink className={`${styles.secondary} ${styles.linkButton}`} href="/actions">Create run plan</ScopedLink></header>
      <div className={styles.attentionToolbar}><label className={styles.field}>Project<input value={projectId} disabled={Boolean(feed.workspace?.scopeLocked)} onChange={(event) => { setProjectId(event.target.value); setPage(1); }} /></label><label className={styles.field}>Environment<select value={environment} disabled={Boolean(feed.workspace?.scopeLocked)} onChange={(event) => { setEnvironment(event.target.value); setPage(1); }}><option value="development">Development</option><option value="production">Production</option><option value="staging">Staging</option></select></label><label className={styles.field}>Status<select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="">All statuses</option><option value="QUEUED">Queued</option><option value="SUBMITTING">Submitting</option><option value="MONITORING">Monitoring</option><option value="VERIFYING">Verifying</option><option value="COMPLETED">Completed</option><option value="FAILED">Failed</option><option value="UNCERTAIN">Uncertain</option><option value="BLOCKED">Blocked</option></select></label><label className={styles.field}>Technology<input value={technology} placeholder="Airflow, dbt, Snowflake" onChange={(event) => { setTechnology(event.target.value); setPage(1); }} /></label><label className={styles.field}>Asset<input value={asset} placeholder="table, DAG, model" onChange={(event) => { setAsset(event.target.value); setPage(1); }} /></label><label className={styles.field}>From<input type="datetime-local" value={since} onChange={(event) => { setSince(event.target.value); setPage(1); }} /></label><label className={styles.field}>To<input type="datetime-local" value={until} onChange={(event) => { setUntil(event.target.value); setPage(1); }} /></label><button className={styles.primary} disabled={busy} onClick={() => void load(1)}>Apply filters</button></div>
      <div className={styles.stateLegend} aria-label="Monitoring outcome legend"><span className={styles.statusGood}><i />Execution and verification passed</span><span className={styles.statusWarn}><i />Waiting, queued, or awaiting continuation</span><span className={styles.statusBad}><i />Failed, blocked, or outcome unknown</span></div>
      {Boolean(feed.error) && <ErrorState title="Monitoring unavailable">{errorMessage(feed.error, "Monitoring is unavailable")}</ErrorState>}
      {Array.isArray(recovery.items) && recovery.items.length > 0 && <section className={styles.panel} aria-label="Operator recovery queue"><header className={styles.panelHead}><div><span className={styles.eyebrow}>OPERATOR ACTION</span><h2>Recovery queue</h2><p>Blocked work stays visible. Each action states whether it reads state or can continue an approved step.</p></div><span className={`${styles.statusPill} ${styles.statusBad}`}>{recovery.items.length} NEED ATTENTION</span></header><div className={styles.summaryList}>{recovery.items.map((item) => { const work = item.work ?? {}; const run = item.run ?? {}; const plan = item.plan ?? {}; const runId = rawId(work.run_id ?? run.run_id); const actions = item.recovery_actions ?? []; return <div className={styles.recoveryRow} key={runId || String(work.work_id)}><div><strong>{text(plan.intent, runId)}</strong><small>{statusLabel(work.state)} · attempt {text(work.attempt, "0")} of {text(work.max_attempts, "—")} · {text(work.last_error, "No recovery reason recorded")}</small></div><div className={styles.recoveryActions}><ScopedLink className={styles.secondary} href={`/actions?run_id=${encodeURIComponent(runId)}#execution-monitor`}>Open run</ScopedLink>{actions.map((action) => <button className={styles.secondary} key={action.action} title={action.allowed ? action.impact : action.disabled_reason ?? "Permission required"} disabled={!action.allowed || busy} onClick={() => void runRecovery(runId, action.action)}>{action.label}</button>)}</div></div>; })}</div></section>}
      {!feed.error && !jobs.length && <div className={styles.infoStrip}><span>i</span><div><strong>{feed.status === "NO_MATCHING_ASSET_FILTER" ? "No persisted jobs match this table filter" : "No persisted jobs match this project and environment"}</strong><p>{feed.status === "NO_MATCHING_ASSET_FILTER" ? "Clear the explicit table filter to see the rest of this project history." : "Approved plans appear here after submission. No external work is started by loading Monitoring."}</p></div></div>}
      <div className={styles.sectionStack}>{groups.map(([sequence, group]) => <section className={styles.panel} key={sequence}><header className={styles.panelHead}><div><h3>{sequence === "unassigned" ? "Individual jobs" : "Selected sequence"}</h3><p>{sequence === "unassigned" ? `${group.length} independent job${group.length === 1 ? "" : "s"}` : `${group.length} ordered step${group.length === 1 ? "" : "s"} · expand to inspect dependencies`}</p></div><div className={styles.monitorGroupActions}><StatusBadge value={group[0].execution_status} />{sequence !== "unassigned" && <button className={styles.secondary} onClick={() => setExpandedSequence((current) => current === sequence ? null : sequence)} aria-expanded={expandedSequence === sequence}>{expandedSequence === sequence ? "Hide steps" : "Show steps"}</button>}</div></header>{expandedSequence === sequence && sequence !== "unassigned" && <div className={styles.sequenceSummary} aria-label={`Steps in ${sequence}`}>{group.map((job, index) => { const step = job.current_step_details && typeof job.current_step_details === "object" ? job.current_step_details as Job : {}; const dependencies = Array.isArray(job.depends_on) ? job.depends_on.map(String).join(", ") : "none recorded"; return <div className={styles.sequenceSummaryRow} key={rawId(job.run_id) || `${sequence}-${index}`}><b>{text(step.sequence ?? job.sequence ?? index + 1)}</b><div><strong>{shortJobName(job)}</strong><small>Depends on: {dependencies}</small></div><div><StatusBadge value={job.execution_status} /><StatusBadge value={job.execution_verification_status ?? job.verification_status} label={statusLabel(job.execution_verification_status ?? job.verification_status, "Not checked")} /></div></div>; })}</div>}<div className={styles.attentionTableWrap}><table className={styles.attentionTable}><thead><tr><th>Job / asset</th><th>Submission</th><th>Execution</th><th>Verification</th><th>Data quality</th><th>Evidence</th><th>Current step</th><th>Last observed</th><th> </th></tr></thead><tbody>{group.map((job) => { const runId = rawId(job.run_id); return <tr key={runId}><td><strong>{shortJobName(job)}</strong><small>{runId || "Unavailable"}</small></td><td><StatusBadge value={job.submission_status} /></td><td><StatusBadge value={job.execution_status} /></td><td><StatusBadge value={job.execution_verification_status ?? job.verification_status} /></td><td><StatusBadge value={job.data_quality_status} label={statusLabel(job.data_quality_status, "Not checked")} /></td><td><StatusBadge value={job.evidence_status} label={statusLabel(job.evidence_status, "Not checked")} /></td><td>{text((job.current_step_details as Job | undefined)?.asset ?? job.current_step)}</td><td>{date(job.last_observation)}{job.stale ? <small className={styles.warningText}>Status needs refresh</small> : null}</td><td><button className={styles.secondary} disabled={!runId} aria-label={`View details for ${runId || "selected job"}`} onClick={() => void selectRun(runId)}>View details</button></td></tr>; })}</tbody></table></div></section>)}</div>
      <nav className={styles.tablePagination} aria-label="Monitoring pages"><span>Project {projectId} · {environment} · Page {feed.page ?? page} · {feed.total ?? 0} total</span><div><button disabled={busy || page <= 1} onClick={() => { const next = page - 1; setPage(next); void load(next); }}>Previous</button><button disabled={busy || !feed.has_next} onClick={() => { const next = page + 1; setPage(next); void load(next); }}>Next</button></div></nav>
    </section>
    {detail && <RunDetails detail={detail} busy={detailBusy} projectId={projectId} environment={environment} onRecovery={(operation) => void runRecovery(detailRunId(detail), operation)} onClear={() => { setDetail(null); setRestoredRunId(""); window.localStorage.removeItem(`ade-monitoring-selected-run:${projectId}:${environment}`); }} />}
  </DraftShell>;
}

function detailRunId(detail: RunDetail): string { return rawId(detail.run_id); }

function RunDetails({ detail, busy, projectId, environment, onRecovery, onClear }: { detail: RunDetail; busy: boolean; projectId: string; environment: string; onRecovery: (operation: string) => void; onClear: () => void }) {
  if (detail.load_error) return <section className={styles.panel} id="selected-run"><header className={styles.panelHead}><div><span className={styles.eyebrow}>SELECTED JOB</span><h2>Unable to load selected run</h2><p><code>{rawId(detail.run_id) || "Unavailable"}</code></p></div><button className={styles.secondary} onClick={onClear}>Clear selected run</button></header><ErrorState title="Run details unavailable"><>{errorMessage(detail.load_error, "The selected run could not be loaded for this project and environment.")} The remembered run was not replaced with another run. Clear it or return to the monitoring list and select a persisted run.</></ErrorState></section>;
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
  return <section className={styles.panel} id="selected-run"><header className={styles.panelHead}><div><span className={styles.eyebrow}>SELECTED JOB</span><h2>{text(plan.intent, detailRunId)}</h2><p><code>{detailRunId || "Unavailable"}</code> · {date(detail.started_at)}</p></div><div><StatusBadge value={detail.state} />{busy && <small> Refreshing details…</small>}</div></header><div className={styles.summaryGrid}><div><small>Project</small><strong>{text(plan.project_id, projectId)}</strong></div><div><small>Environment</small><strong>{text(plan.environment, environment)}</strong></div><div><small>Execution outcome</small><strong>{statusLabel(detail.execution_status ?? detail.state)}</strong></div><div><small>Execution verification</small><strong>{statusLabel(detail.execution_verification_status ?? detail.verification_status, "Not checked")}</strong></div><div><small>Data-quality outcome</small><strong>{statusLabel(detail.data_quality_status, "Not checked")}</strong></div><div><small>Evidence availability</small><strong>{statusLabel(detail.evidence_status, "Not checked")}</strong></div></div>{hasAttention && <div className={styles.infoStrip}><strong>Status needs attention</strong><p>{uncertaintyMessage}</p></div>}{recoveryActions.length > 0 && <section className={styles.recoveryCallout}><h3>Recovery actions</h3><p>These actions are scoped to this run. Reconcile reads external state; continue only advances approved work.</p><div className={styles.recoveryActions}>{recoveryActions.map((action) => <button className={styles.secondary} key={String(action.action)} disabled={action.allowed === false || busy} title={String(action.allowed === false ? action.disabled_reason ?? "Permission required" : action.impact ?? "Scoped recovery action")} onClick={() => onRecovery(String(action.action))}>{String(action.label ?? action.action)}</button>)}</div></section>}<div className={styles.sectionStack}><section><h3>Lifecycle and dependencies</h3><div className={styles.summaryList}>{dependencies.map((item) => <div className={styles.summaryRow} key={String(item.sequence)}><span>{String(item.sequence)} · {text(item.asset)}<small>{text(item.kind)} · depends on {Array.isArray(item.depends_on) && item.depends_on.length ? item.depends_on.map((dependency) => String(dependency)).join(", ") : "none"}</small></span><StatusBadge value={item.status} /></div>)}</div></section><section><h3>External execution identifiers</h3><div className={styles.summaryList}>{identifiers.length ? identifiers.map((item, index) => <div className={styles.summaryRow} key={`${String(item.value)}-${index}`}><span>{text(item.technology)} · {text(item.kind)}<small><code>{String(item.value)}</code> · step {String(item.step_sequence ?? "—")}</small></span>{typeof item.url === "string" ? <a href={item.url} target="_blank" rel="noreferrer">Open external run</a> : <StatusBadge value="VERIFIED" label="Observed" />}</div>) : <div className={styles.summaryRow}><span>No external identifier persisted yet</span><strong>—</strong></div>}</div></section><section><h3>Attempt history</h3><div className={styles.summaryList}>{attempts.length ? attempts.map((item) => <div className={styles.summaryRow} key={String(item.attempt_id)}><span>Attempt {String(item.attempt)} · {text(item.worker_id)}<small>Claimed {date(item.claimed_at)} · released {date(item.released_at)}{item.error ? ` · ${text(item.error)}` : ""}</small></span><StatusBadge value={item.state} /></div>) : <div className={styles.summaryRow}><span>No worker attempts recorded</span><strong>—</strong></div>}</div></section><section><h3>Step evidence</h3><div className={styles.summaryList}>{steps.map((item) => <div className={styles.summaryRow} key={String((item.step as Job)?.sequence)}><span>{text((item.step as Job)?.asset)}<small>Execution: {statusLabel(outcomeStatus(item, "execution") ?? (item.execution as Job)?.status)} · Verification: {statusLabel(outcomeStatus(item, "execution_verification") ?? (item.verification as Job)?.status, "Not checked")} · Data quality: {statusLabel(outcomeStatus(item, "data_quality"), "Not checked")}</small></span><Link href={exactEvidence}>Open exact evidence</Link></div>)}</div></section></div></section>;
}
