"use client";

import { useEffect, useMemo, useState } from "react";
import DraftShell from "../DraftShell";
import styles from "../workflow.module.css";
import local from "./actions.module.css";
import { scopedApiUrl } from "../../lib/client-workspace";
import { PageHeader, StatusBadge } from "../components/ui";

type Capability = { available: boolean; asset_count?: number; targets?: number; stages?: number; file_formats?: number };
type Capabilities = {
  status: string;
  analysis_run_id: string;
  approval: { binding: string; single_use: boolean; maximum_ttl_minutes: number };
  capabilities: Record<string, Capability | string[]>;
  allowlists: Record<string, string[]>;
};
type Asset = { asset_id: string; name: string; kind: string; layer?: string };
type Step = { sequence: number; kind: string; asset: string; parameters: Record<string, unknown>; evidence_ids: string[] };
type ExecutionMode = "single_job" | "selected_sequence" | "end_to_end";
type OperationKind = "custom" | "airflow_trigger" | "dbt_execute" | "snowflake_copy_into" | "snowpipe_refresh" | "quality_checks";
type Plan = { plan_id: string; plan_hash: string; state: string; intent: string; mode?: ExecutionMode; steps: Step[]; requires_human_approval: boolean };
type Planned = {
  status: string; mode?: ExecutionMode; reason?: string; next_step?: string; capability?: string; target?: Asset; resolution?: Record<string, unknown>;
  topology?: Record<string, Asset[]>; planner?: Record<string, unknown>; plan?: Plan; candidates?: Asset[];
};
type Run = {
  run_id: string;
  plan_id?: string;
  state: string;
  dry_run: boolean;
  started_at?: string;
  completed_at?: string | null;
  pending_step_sequence?: number;
  plan?: Plan;
  steps: Array<{ step: Step; execution: Record<string, unknown>; verification: Record<string, unknown> }>;
  error?: unknown;
};
type Approval = { approval_id: string; approved_by: string; expires_at: string; plan_hash: string };
type ReadinessItem = { name: string; status: string; reason?: string; details?: Record<string, unknown> };
type DemoReadiness = { readiness?: ReadinessItem[]; execution_boundary?: Record<string, unknown>; generated_at?: string };
type AIReview = {
  review_id: string;
  status: string;
  evidence_state?: string;
  review_case: string;
  provider?: string | null;
  model?: string | null;
  prompt_version?: string;
  rationale?: string;
  uncertainty?: string;
  next_action?: string;
  limitations?: string[];
  observed_facts?: Array<{ fact_id: string; statement: string; evidence_ids?: string[] }>;
  hypotheses?: Array<{ statement: string; classification: string; confidence: number; evidence_ids?: string[] }>;
  evidence?: Array<{ evidence_id: string; label: string; href: string; status?: string }>;
  rca?: { what_failed?: string; impact?: string; likely_cause?: { classification?: string; statement?: string }; next_action?: string; limitations?: string[] };
  usage?: { total_tokens?: number };
  latency_ms?: number;
  approval?: { required?: boolean; status?: string; execution_authority?: string };
};

async function call(body?: Record<string, unknown>, path = "/api/actions") {
  const response = await fetch(scopedApiUrl(path), body ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Action Center request failed");
  return value;
}

const labels: Record<string, string> = {
  airflow_trigger: "Airflow trigger",
  dbt_execute: "dbt execution",
  snowflake_copy_into: "Snowflake COPY INTO",
  snowpipe_refresh: "Snowpipe refresh",
  snowflake_task_execute: "Snowflake Task",
  quality_checks: "Quality checks",
};

function capabilityDetail(key: string, value: Capability) {
  if (key === "snowflake_copy_into") {
    return `${value.targets ?? 0} targets · ${value.stages ?? 0} stages · ${value.file_formats ?? 0} formats`;
  }
  const noun = key === "airflow_trigger" ? "allow-listed DAGs" : key === "dbt_execute" ? "allow-listed selectors" : key === "quality_checks" ? "typed dbt test selectors" : "discovered objects";
  return `${value.asset_count ?? 0} ${noun}`;
}

function statusLabel(value: unknown, fallback = "Not available"): string {
  const state = displayMessage(value, fallback).toUpperCase();
  const labels: Record<string, string> = {
    AWAITING_APPROVAL: "Awaiting approval", AWAITING_CONTINUATION: "Awaiting continuation", DRY_RUN: "Dry run",
    MONITORING: "Waiting for observation", OUTCOME_UNKNOWN: "Outcome unknown — reconcile", NOT_RUN: "Not run",
    NOT_CHECKED: "Not checked", UNAVAILABLE: "Unavailable", NOT_DISCOVERED: "Not discovered",
  };
  return labels[state] ?? displayMessage(value, fallback).replaceAll("_", " ");
}

const DEFAULT_INTENT = "";
const operationPresets: Array<{ value: OperationKind; label: string; prefix: string }> = [
  { value: "custom", label: "Describe a job or sequence", prefix: "" },
  { value: "airflow_trigger", label: "Airflow DAG", prefix: "Run only this Airflow DAG: " },
  { value: "dbt_execute", label: "dbt model or test", prefix: "Run only this dbt selector: " },
  { value: "snowflake_copy_into", label: "COPY command", prefix: "Run only this COPY command: " },
  { value: "snowpipe_refresh", label: "Snowpipe refresh", prefix: "Refresh only this Snowpipe: " },
  { value: "quality_checks", label: "Quality checks", prefix: "Run only these quality checks: " },
];
function inferExecutionMode(value: string): ExecutionMode {
  const normalized = value.toLowerCase();
  if (/\b(all|complete|entire|full|end[- ]to[- ]end|upstream|downstream)\b/.test(normalized)) return "end_to_end";
  if (/\bthen\b|->|→/.test(normalized)) return "selected_sequence";
  return "single_job";
}

function displayMessage(value: unknown, fallback = "") {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const item = value as Record<string, unknown>;
    if (typeof item.message === "string") return item.message;
    if (typeof item.error === "string") return item.error;
    try { return JSON.stringify(value); } catch { return fallback; }
  }
  return value === null || value === undefined ? fallback : String(value);
}

export default function ActionsPage() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [intent, setIntent] = useState(DEFAULT_INTENT);
  const [mode, setMode] = useState<ExecutionMode>(() => inferExecutionMode(DEFAULT_INTENT));
  const [modeExplicit, setModeExplicit] = useState(false);
  const [operationKind, setOperationKind] = useState<OperationKind>("custom");
  const [operationTarget, setOperationTarget] = useState("");
  const [planned, setPlanned] = useState<Planned | null>(null);
  const [dryRun, setDryRun] = useState<Run | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [rejectionReason, setRejectionReason] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const [demoReadiness, setDemoReadiness] = useState<DemoReadiness | null>(null);
  const [readinessBusy, setReadinessBusy] = useState(false);
  const [aiReview, setAiReview] = useState<AIReview | null>(null);
  const [aiReviewBusy, setAiReviewBusy] = useState(false);
  const [hasActiveScope, setHasActiveScope] = useState(false);
  const [workspaceScope, setWorkspaceScope] = useState<{ project: string; environment: string } | null>(null);

  const load = async () => {
    try {
      const requestedRunId = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("run_id") : null;
      const value = await call(undefined, requestedRunId ? `/api/actions?run_id=${encodeURIComponent(requestedRunId)}` : "/api/actions");
      setCapabilities(value.capabilities);
      setHasActiveScope(typeof value.source_table_scope_id === "string" && value.source_table_scope_id.length > 0);
      if (value.workspace && typeof value.workspace === "object") {
        const workspace = value.workspace as { projectId?: unknown; environment?: unknown };
        if (typeof workspace.projectId === "string" && typeof workspace.environment === "string") {
          setWorkspaceScope({ project: workspace.projectId, environment: workspace.environment });
        }
      }
      const persistedRuns = (value.runs?.items ?? []) as Run[];
      const activeRun = (requestedRunId ? persistedRuns.find((item) => item.run_id === requestedRunId) : null)
        ?? (!requestedRunId ? persistedRuns.find((item) => ["QUEUED", "SUBMITTING", "VERIFYING", "MONITORING", "AWAITING_CONTINUATION", "RUNNING", "UNCERTAIN", "OUTCOME_UNKNOWN"].includes(item.state)) : null);
      if (activeRun) {
        setRun((current) => current?.run_id === activeRun.run_id ? activeRun : current ?? activeRun);
        setPlanned((current) => current ?? (activeRun.plan ? { status: activeRun.plan.state, plan: activeRun.plan } : null));
      }
    } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "Unable to load" }); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const project = params.get("project_id");
    const environment = params.get("environment");
    if (project && environment) setWorkspaceScope({ project, environment });
  }, []);

  const loadDemoReadiness = async (checkConnectivity = false, verifyModel = false) => {
    setReadinessBusy(true);
    try {
      const query = new URLSearchParams();
      if (checkConnectivity) query.set("check_connectivity", "true");
      if (verifyModel) query.set("verify_model", "true");
      const suffix = query.toString() ? `?${query.toString()}` : "";
      const response = await fetch(scopedApiUrl(`/api/demo/readiness${suffix}`), { cache: "no-store" });
      const value = await response.json() as DemoReadiness & { error?: string };
      if (!response.ok) throw new Error(value.error || "Demo readiness request failed");
      setDemoReadiness(value);
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "Unable to load demo readiness" });
    } finally { setReadinessBusy(false); }
  };
  useEffect(() => { if (hasActiveScope) void loadDemoReadiness(); else setDemoReadiness(null); }, [hasActiveScope]);

  useEffect(() => {
    if (!run || !["QUEUED", "SUBMITTING", "VERIFYING", "MONITORING", "AWAITING_CONTINUATION", "OUTCOME_UNKNOWN", "UNCERTAIN", "RUNNING"].includes(run.state)) return;
    const timer = window.setInterval(() => {
      void call({ action: "status", runId: run.run_id }).then((value) => {
        setRun(value as Run);
      }).catch(() => { /* keep the last truthful state visible */ });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [run?.run_id, run?.state]);

  const act = async (action: string, payload: Record<string, unknown> = {}) => {
    setBusy(action); setNotice(null);
    try {
      const value = await call({ action, ...payload });
      if (action === "plan") { setPlanned(value); setDryRun(null); setApproval(null); setRun(null); setConfirmed(false); setExpandedStep(null); }
      if (action === "dry-run") setDryRun(value);
      if (action === "approve") setApproval(value);
      if (action === "reject") { setPlanned((current) => current ? { ...current, plan: value } : current); setApproval(null); }
      if (action === "execute" || action === "resume" || action === "reconcile" || action === "verify") setRun(value);
      const planStatus = action === "plan" ? String(value.status ?? "") : "";
      const planBlocked = action === "plan" && ["BLOCKED", "CAPABILITY_UNAVAILABLE", "NEEDS_CLARIFICATION"].includes(planStatus);
      setNotice({ tone: planBlocked ? "error" : "success", text: action === "plan" ? (planBlocked ? `${planStatus}: no executable plan was created.` : "Evidence-backed plan created. Nothing has executed.") : `${action} completed.` });
      await load();
    } catch (error) { setNotice({ tone: "error", text: error instanceof Error ? error.message : "Action failed" }); }
    finally { setBusy(null); }
  };

  const invokeAiReview = async (reviewCase: "success" | "failed" | "incomplete_evidence") => {
    setAiReviewBusy(true); setNotice(null);
    try {
      const firstAsset = activePlan?.steps?.[0]?.asset ?? null;
      const response = await fetch(scopedApiUrl("/api/ai-reviews"), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ review_case: reviewCase, run_id: run?.run_id ?? null, selected_asset: firstAsset }),
      });
      const value = await response.json() as { review?: AIReview; error?: string };
      if (!response.ok || !value.review) throw new Error(value.error || "AI review could not be invoked");
      setAiReview(value.review);
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "AI review failed" });
    } finally { setAiReviewBusy(false); }
  };

  const plan = planned?.plan;
  const activePlan = plan ?? run?.plan;
  const monitoredStep = run ? (run.steps.find((item) => item.step.sequence === run.pending_step_sequence) ?? run.steps[run.steps.length - 1]) : undefined;
  const monitoredExecution = monitoredStep?.execution ?? {};
  const runtimeState = String(monitoredExecution.state ?? monitoredStep?.verification.runtime_state ?? "WAITING").toUpperCase();
  const capabilityRows = useMemo(() => capabilities ? Object.entries(capabilities.capabilities).filter(([, value]) => typeof value === "object" && value !== null && !Array.isArray(value) && "available" in value) as Array<[string, Capability]> : [], [capabilities]);
  const selectedOperation = operationPresets.find((item) => item.value === operationKind) ?? operationPresets[0];
  const updateOperation = (value: OperationKind) => {
    setOperationKind(value);
    const preset = operationPresets.find((item) => item.value === value) ?? operationPresets[0];
    if (value !== "custom") {
      setMode(value === "quality_checks" ? "single_job" : "single_job");
      setModeExplicit(true);
      setIntent(`${preset.prefix}${operationTarget}`.trimEnd());
    }
  };
  const updateOperationTarget = (value: string) => {
    setOperationTarget(value);
    if (operationKind !== "custom") setIntent(`${selectedOperation.prefix}${value}`.trimEnd());
  };

  return <DraftShell active="actions">
    <PageHeader eyebrow="AUTOMATED DATA QUALITY / JOBS" title="Run jobs" description="Choose one operation or an explicit sequence, preview the exact scope, approve it, then track execution and quality separately." status={<StatusBadge value={capabilities?.status ?? "CONNECTING"} label={statusLabel(capabilities?.status ?? "CONNECTING")} />} />
    <div className={local.scopeContext} aria-label="Current project and environment scope"><span>Scope</span><label>Project<input aria-label="Project scope" value={workspaceScope?.project ?? ""} placeholder="Loading project scope" readOnly /></label><label>Environment<select aria-label="Environment scope" value={workspaceScope?.environment ?? ""} disabled={!workspaceScope} onChange={(event) => { const next = new URL(window.location.href); next.searchParams.set("environment", event.target.value); window.location.assign(next.toString()); }}><option value="">Loading environment scope</option><option value="development">Development</option><option value="staging">Staging</option><option value="production">Production</option></select></label></div>
    {notice && <div className={notice.tone === "error" ? styles.dangerStrip : styles.successStrip}>{notice.text}</div>}
    <nav className={local.executionFlow} aria-label="Job execution flow"><a className={local.executionFlowActive} href="#plan-workspace"><b>1</b><span>Choose</span><small>Operation and scope</small></a><a href="#preview-plan"><b>2</b><span>Preview</span><small>Exact steps</small></a><a href="#approval-control"><b>3</b><span>Approve</span><small>Human approval</small></a><a href="#execution-monitor"><b>4</b><span>Track results</span><small>Run and quality outcome</small></a></nav>
    {demoReadiness && <section className={`${styles.panel} ${local.readiness}`} aria-label="Controlled live-demo readiness">
      <header className={styles.panelHead}><div><span className={styles.eyebrow}>CONTROLLED DEMO BASELINE</span><h2>Demo readiness</h2><p>Configuration and read-only checks for the selected project. This panel never runs or resets a pipeline.</p></div><div className={local.readinessActions}><button className={styles.secondary} disabled={readinessBusy} onClick={() => void loadDemoReadiness(true)}>{readinessBusy ? "Checking…" : "Check connectivity"}</button><button className={styles.secondary} disabled={readinessBusy} onClick={() => void loadDemoReadiness(false, true)}>{readinessBusy ? "Verifying…" : "Verify model"}</button></div></header>
      <div className={local.readinessGrid}>{(demoReadiness.readiness ?? []).map((item) => <article key={item.name}><span className={`${local.readinessStatus} ${item.status === "READY" ? local.readinessReady : item.status === "NOT_CHECKED" ? local.readinessNotChecked : local.readinessUnavailable}`}>{item.status.replaceAll("_", " ")}</span><strong>{item.name.replaceAll("_", " ")}</strong>{item.reason && <small>{item.reason}</small>}</article>)}</div>
      <small className={local.readinessFootnote}>Generated {demoReadiness.generated_at ? new Date(demoReadiness.generated_at).toLocaleTimeString() : "just now"}. Static artifacts are not execution evidence; certification remains a human decision.</small>
    </section>}
    <nav className={local.viewTabs} aria-label="Action Center views">
      <a href="#plan-workspace">Plan workspace</a>
      <a className={run ? local.viewTabActive : ""} href="#execution-monitor">Execution monitor {run ? <StatusBadge value={run.state} label={statusLabel(run.state)} /> : <small>No active run</small>}</a>
    </nav>

    {run && !run.dry_run && <section id="execution-monitor" className={`${styles.panel} ${local.monitor}`} aria-live="polite">
      <header className={styles.panelHead}><div><span className={styles.eyebrow}>LIVE EXECUTION</span><h2>Execution monitor</h2><p>This is the persisted run for the approved workflow. Refreshing this page will not create another run.</p></div><StatusBadge value={run.state} label={statusLabel(run.state)} /></header>
      <div className={local.monitorGrid}>
        <div><small>Workflow</small><strong>{activePlan?.intent ?? "Approved workflow"}</strong></div>
        <div><small>Current step</small><strong>{monitoredStep ? `${monitoredStep.step.sequence} of ${run.steps.length} · ${monitoredStep.step.asset}` : "No pending step"}</strong></div>
        <div><small>Runtime state</small><strong>{runtimeState}</strong></div>
        <div><small>External run</small><code>{String(monitoredExecution.external_run_id ?? monitoredExecution.dag_run_id ?? "Not assigned")}</code></div>
      </div>
      {run.state === "MONITORING" && <div className={local.monitorMessage}><strong>Waiting for the external job to finish.</strong><span>The approved run is still active; downstream steps remain paused until external verification passes.</span></div>}
      {run.state === "AWAITING_CONTINUATION" && <div className={local.monitorMessage}><strong>Verification passed; continuation is waiting.</strong><span>The current step is preserved. Continue only the approved downstream steps when you are ready.</span></div>}
      {(run.state === "OUTCOME_UNKNOWN" || run.state === "UNCERTAIN") && <div className={local.monitorMessage}><strong>External outcome is unknown.</strong><span>The system will reconcile the external operation before any retry. No duplicate submission is attempted.</span></div>}
      <div className={local.runActions}>{["MONITORING", "AWAITING_CONTINUATION"].includes(run.state) && <button className={styles.primary} disabled={busy !== null} onClick={() => void act("resume", { planId: activePlan?.plan_id ?? run.plan_id, runId: run.run_id })}>{busy === "resume" ? "Queuing…" : run.state === "AWAITING_CONTINUATION" ? "Continue approved sequence" : "Check completion and continue"}</button>}{["OUTCOME_UNKNOWN", "UNCERTAIN"].includes(run.state) && <button className={styles.primary} disabled={busy !== null} onClick={() => void act("reconcile", { planId: activePlan?.plan_id ?? run.plan_id, runId: run.run_id })}>{busy === "reconcile" ? "Queuing…" : "Reconcile outcome"}</button>}{["COMPLETED", "FAILED"].includes(run.state) && <button className={styles.secondary} disabled={busy !== null} onClick={() => void act("verify", { planId: activePlan?.plan_id ?? run.plan_id, runId: run.run_id })}>{busy === "verify" ? "Verifying…" : "Verify now without rerunning"}</button>}<button className={styles.secondary} disabled={aiReviewBusy} onClick={() => void invokeAiReview(run.state === "COMPLETED" ? "success" : run.state === "FAILED" ? "failed" : "incomplete_evidence")}>{aiReviewBusy ? "Reviewing…" : "Run bounded AI review"}</button></div>
    </section>}

    {aiReview && <AIReviewPanel review={aiReview} />}

    <details className={local.collapsiblePanel}>
      <summary>Capabilities available for this workspace <span>{capabilityRows.length} discovered</span></summary>
      <section className={local.capabilities} aria-label="Live action capabilities">
        {capabilityRows.map(([key, value]) => <article key={key} className={value.available ? local.available : local.unavailable}><span>{value.available ? "AVAILABLE" : "NOT DISCOVERED"}</span><strong>{labels[key] ?? key}</strong><small>{capabilityDetail(key, value)}</small></article>)}
      </section>
    </details>

    <div className={local.layout}><div className={local.main}>
      <section id="plan-workspace" className={styles.panel}><header className={styles.panelHead}><div><h2>1. Choose the operation</h2><p>Select the smallest requested scope. Dependencies may be discovered for explanation, but are never added silently.</p></div><span>REQUEST SCOPE</span></header><div className={local.operationBar}><label>Operation<select aria-label="Requested operation" value={operationKind} onChange={(event) => updateOperation(event.target.value as OperationKind)}>{operationPresets.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>Job, model, table, pipe or sequence<input aria-label="Requested job target" value={operationTarget} onChange={(event) => updateOperationTarget(event.target.value)} placeholder={operationKind === "custom" ? "e.g. COPY, then dbt model" : "Enter the exact name or qualified target"} /></label><small>{operationKind === "custom" ? "Use plain language for a selected sequence or end-to-end request." : `Planner request: ${selectedOperation.prefix || selectedOperation.label}`}</small></div><div className={local.scopeRow}><label>Execution mode<select value={mode} onChange={(event) => { setMode(event.target.value as ExecutionMode); setModeExplicit(true); }}><option value="single_job">Single job — exactly one requested job</option><option value="selected_sequence">Selected sequence — only named jobs, in order</option><option value="end_to_end">End-to-end — explicit dependency chain</option></select></label><small>{modeExplicit ? `Explicit mode: ${mode.replaceAll("_", " ")}. The planner will not widen this request.` : `Suggested mode: ${mode.replaceAll("_", " ")}, inferred from the request. Editing the request will update this suggestion until you choose a mode.`}</small></div><textarea aria-label="Execution request" className={local.intent} value={intent} onChange={(event) => { const next = event.target.value; setIntent(next); if (!modeExplicit) setMode(inferExecutionMode(next)); }} /><div className={local.promptFooter}><small>No command text or approval is accepted from the AI.</small><button className={styles.primary} disabled={busy !== null || intent.trim().length < 3} onClick={() => void act("plan", { intent, mode, operationKind, requestedTarget: operationTarget })}>{busy === "plan" ? "Analyzing scope…" : "Preview exact plan"}</button></div></section>

      {planned && !plan && <section className={styles.panel}><div className={styles.dangerStrip}><strong>{statusLabel(planned.status)}</strong><br />{planned.reason}{planned.next_step && <p className={local.nextStep}>{planned.next_step}</p>}</div>{planned.candidates?.length ? <div className={local.candidates}>{planned.candidates.map((item) => <button key={item.asset_id} onClick={() => void act("plan", { intent, targetAsset: item.name })}><strong>{item.name}</strong><small>{item.kind}</small></button>)}</div> : null}</section>}

      {plan && <>
        <span id="preview-plan" className={local.flowAnchor} aria-hidden="true" />
        <section className={styles.panel}><header className={styles.panelHead}><div><h2>2. Evidence-backed topology</h2><p>Arranged by pipeline layer; empty technologies are not fabricated.</p></div><span>{planned?.resolution?.agent_used ? "AI RESOLVED" : "DETERMINISTIC"}</span></header><div className={local.topology}>{Object.entries(planned?.topology ?? {}).map(([layer, assets]) => <div key={layer} className={local.lane}><header><strong>{layer}</strong><span>{assets.length}</span></header><div>{assets.length ? assets.slice(0, 14).map((asset) => <article key={asset.asset_id}><small>{asset.kind}</small><strong>{asset.name}</strong></article>) : <p>No related assets</p>}</div>{assets.length > 14 && <footer>+ {assets.length - 14} more in this lineage scope</footer>}</div>)}</div></section>

      <section className={styles.panel}><header className={styles.panelHead}><div><h2>3. Exact execution plan</h2><p>Every step is typed, evidence-bound and covered by the same immutable plan hash. Click a step to inspect its full scope.</p></div><StatusBadge value={plan.state} label={statusLabel(plan.state)} /></header><div className={local.planMeta}><span>Mode <strong>{(plan.mode ?? "single_job").replaceAll("_", " ")}</strong></span><span>Plan <code>{plan.plan_id}</code></span><span>Hash <code>{plan.plan_hash.slice(0, 16)}…</code></span></div><div className={local.steps}>{plan.steps.map((step) => { const selector = typeof step.parameters.selector === "string" ? step.parameters.selector : null; const isExpanded = expandedStep === step.sequence; const transformation = planned?.topology?.transformation ?? []; return <article key={step.sequence}><b>{step.sequence}</b><button className={local.stepButton} onClick={() => setExpandedStep(isExpanded ? null : step.sequence)} aria-expanded={isExpanded}><small>{step.kind.replaceAll("_", " ")}</small><strong>{step.asset}</strong>{selector && <em className={local.selector}>dbt selector: {selector}</em>}<code>{JSON.stringify(step.parameters)}</code></button><span>{step.evidence_ids.length} evidence</span>{isExpanded && <div className={local.stepDetails}>{step.kind === "airflow_trigger" ? <><strong>Airflow job</strong><p>DAG <code>{String(step.parameters.dag_id ?? step.asset)}</code> will be triggered with the approved configuration.</p><small>Runtime definition and task graph remain read-only; execution evidence will include the returned DAG run ID.</small></> : selector ? <><strong>dbt scope preserved</strong><p>Command: <code>{String(step.parameters.verb ?? "run")}</code> · selector: <code>{selector}</code></p><ul>{transformation.map((asset) => <li key={asset.asset_id}><span>{asset.kind}</span>{asset.name}</li>)}</ul><small>Upstream/downstream expansion is shown only when requested by the selected execution mode.</small></> : <><strong>Full step parameters</strong><pre>{JSON.stringify(step.parameters, null, 2)}</pre></>}</div>}</article>; })}</div></section>

        <span id="approval-control" className={local.flowAnchor} aria-hidden="true" />
        <section className={local.control}><div><strong>3. Approve the preview</strong><p>Dry-run first. Approval is single-use, expires in 15 minutes and is invalidated by any plan change.</p></div><div className={local.controlActions}><button className={styles.secondary} disabled={busy !== null || plan.state === "REJECTED"} onClick={() => void act("dry-run", { planId: plan.plan_id })}>{busy === "dry-run" ? "Preparing…" : "Run safe dry-run"}</button><label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> I reviewed the exact steps and impact</label><button className={styles.secondary} disabled={!dryRun || !confirmed || busy !== null || Boolean(approval) || plan.state === "REJECTED"} onClick={() => void act("approve", { planId: plan.plan_id })}>{approval ? "Approved" : "Approve once"}</button><button className={styles.dangerButton} disabled={!confirmed || !rejectionReason.trim() || busy !== null || plan.state === "REJECTED"} onClick={() => void act("reject", { planId: plan.plan_id, reason: rejectionReason })}>{busy === "reject" ? "Rejecting…" : "Reject plan"}</button><button className={styles.primary} disabled={!approval || busy !== null || Boolean(run)} onClick={() => void act("execute", { planId: plan.plan_id, approvalId: approval?.approval_id })}>{busy === "execute" ? "Executing…" : "Execute approved plan"}</button><input className={local.rejectReason} value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} placeholder="Reason required to reject" aria-label="Rejection reason" /></div></section>
      </>}

      {dryRun && <RunEvidence title="Dry-run evidence" run={dryRun} />}
      {run && <RunEvidence title="Live execution evidence" run={run} />}
    </div>

    <aside className={local.side}>
      {planned?.status === "BLOCKED" && <section className={styles.panel}><h3>Permanent blocks</h3><div className={local.blocks}>{((capabilities?.capabilities.permanent_blocks as string[]) ?? []).map((item) => <p key={item}>× {item}</p>)}</div></section>}
      <details className={`${styles.panel} ${local.collapsiblePanel}`} open><summary>Approval contract <span>Binding and expiry</span></summary><div className={local.collapsibleBody}><dl><div><dt>Binding</dt><dd>{capabilities?.approval.binding ?? "—"}</dd></div><div><dt>Single use</dt><dd>{capabilities?.approval.single_use ? "Yes" : "—"}</dd></div><div><dt>Maximum TTL</dt><dd>{capabilities?.approval.maximum_ttl_minutes ?? "—"} min</dd></div></dl></div></details>
    </aside></div>
  </DraftShell>;
}

function RunEvidence({ title, run }: { title: string; run: Run }) {
  return <section className={styles.panel}><header className={styles.panelHead}><div><h2>{title}</h2><p>{run.run_id}</p></div><StatusBadge value={run.state} label={statusLabel(run.state)} /></header>{run.error ? <div className={styles.dangerStrip}>{displayMessage(run.error, "Action run failed")}</div> : null}<div className={local.runSteps}>{run.steps.map((item) => <article key={item.step.sequence}><div><b>{item.step.sequence}</b><strong>{item.step.asset}</strong></div><span>Execution: {statusLabel(item.execution.status, "Not checked")}</span><span>Verification: {statusLabel(item.verification.status, "Not checked")}</span><details><summary>Evidence details</summary><pre>{JSON.stringify({ execution: item.execution, verification: item.verification }, null, 2)}</pre></details></article>)}</div></section>;
}

function AIReviewPanel({ review }: { review: AIReview }) {
  return <section className={styles.panel} aria-label="Bounded AI review">
    <header className={styles.panelHead}><div><span className={styles.eyebrow}>EVIDENCE-BOUND ADVISORY REVIEW</span><h2>AI review</h2><p>{review.review_case.replaceAll("_", " ")} · {review.prompt_version ?? "version not recorded"}</p></div><span>{review.status.replaceAll("_", " ")}</span></header>
    <div className={local.monitorGrid}><div><small>Provider</small><strong>{review.provider ?? "Not invoked"} · {review.model ?? "—"}</strong></div><div><small>Evidence</small><strong>{review.evidence_state ?? "not checked"}</strong></div><div><small>Latency</small><strong>{review.latency_ms ?? 0} ms</strong></div><div><small>Usage</small><strong>{review.usage?.total_tokens ?? 0} tokens</strong></div></div>
    {review.rca && <div className={local.monitorMessage}><strong>What failed</strong><span>{review.rca.what_failed}</span><strong>Impact</strong><span>{review.rca.impact}</span><strong>Likely cause</strong><span>{review.rca.likely_cause?.classification?.replaceAll("_", " ")}: {review.rca.likely_cause?.statement}</span><strong>Next action</strong><span>{review.rca.next_action}</span></div>}
    {review.rationale && <p>{review.rationale}</p>}
    {review.uncertainty && <p><strong>Uncertainty:</strong> {review.uncertainty}</p>}
    {review.hypotheses?.length ? <details><summary>Hypotheses</summary>{review.hypotheses.map((item, index) => <p key={`${item.classification}-${index}`}>{item.classification.replaceAll("_", " ")} · {Math.round(item.confidence * 100)}% · {item.statement}</p>)}</details> : null}
    {review.evidence?.length ? <details><summary>Exact evidence links</summary><ul>{review.evidence.map((item) => <li key={item.evidence_id}><a href={item.href}>{item.label}</a> <small>{item.status ?? "not checked"}</small></li>)}</ul></details> : null}
    {review.approval?.required && <div className={styles.dangerStrip}>Advisory execution proposal is pending human approval. This review cannot authorize or execute it.</div>}
  </section>;
}
