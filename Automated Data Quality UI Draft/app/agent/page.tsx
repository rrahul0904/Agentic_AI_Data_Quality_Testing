"use client";

import { useEffect, useState } from "react";
import DraftShell from "../DraftShell";
import styles from "../workflow.module.css";
import { currentWorkspaceParams, scopedApiUrl } from "../../lib/client-workspace";
import local from "./agent.module.css";

type EvidenceLink = { label?: string; type?: string; status?: string; reference?: string; href?: string | null };
type AgentUsage = { input_tokens?: number; output_tokens?: number; reasoning_tokens?: number; cache_read_tokens?: number; cache_write_tokens?: number };
type AgentHistoryItem = {
  invocation_id?: string;
  question?: string;
  answer?: string;
  status?: string;
  error?: string | Record<string, unknown>;
  provider?: string;
  model?: string | null;
  usage?: AgentUsage | null;
  latency_ms?: number | null;
  scope?: { project_id?: string; environment?: string; selected_asset?: string | null; run_id?: string | null };
  evidence_references?: string[];
  tools_used?: string[];
  created_at?: string;
};
type AirflowDag = { dag_id?: string; is_paused?: boolean; timetable_description?: string; timetable_summary?: string };
type OrchestrationRun = { dag_id?: string; status?: string; run_id?: string | null; started_at?: string | null; ended_at?: string | null };
type AgentResult = {
  status?: string;
  request_type?: string;
  quality_scope?: string;
  source?: string;
  dags?: AirflowDag[];
  runs?: unknown[];
  task_instances?: unknown[];
  failed_tasks?: unknown[];
  task_instance_errors?: unknown[];
  orchestration?: { phases?: Array<{ name?: string; dags?: OrchestrationRun[] }>; runtime_runs_observed?: number; status?: string };
  freshness?: string;
  last_refreshed?: string;
  scope_state?: string;
  scope_enforced?: boolean;
  refresh_error?: string | null;
};
type AgentResponse = {
  question?: string;
  answer?: string;
  result?: AgentResult | unknown;
  supporting_facts?: Array<{ fact?: string; status?: string }>;
  uncertainty?: string[];
  next_action?: string;
  evidence_links?: EvidenceLink[];
  agent?: { status?: string; failure_kind?: string; error?: string | Record<string, unknown>; provider?: string; model?: string | null; usage?: AgentUsage | null; latency_ms?: number | null; query_failures?: Array<Record<string, unknown>> };
  evidence?: { tools_used?: string[]; data_sources?: string[]; records?: EvidenceLink[]; scope?: Record<string, unknown>; mode?: string; timestamp?: string };
  tools_used?: string[];
  data_sources?: string[];
  error?: string;
};

function resultRecord(value: unknown): AgentResult {
  return value && typeof value === "object" ? value as AgentResult : {};
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function objectList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : [];
}

function formatDateTime(value?: string | null): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function formatDuration(start?: string | null, end?: string | null): string {
  if (!start || !end) return "duration not recorded";
  const elapsed = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(elapsed) || elapsed < 0) return "duration not recorded";
  const seconds = Math.round(elapsed / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function humanStatus(value?: string | null): string {
  const status = String(value ?? "").toUpperCase();
  if (status === "VERIFIED_TOOL_RESPONSE" || status === "TOOL_EVIDENCE_ONLY") return "Evidence collected";
  if (status === "LIVE_RESPONSE") return "AI explanation completed";
  if (status === "LIVE_PROVIDER_TIMEOUT") return "AI provider timed out";
  if (status === "LIVE_QUERY_LIMIT_REACHED") return "Evidence-query limit reached";
  if (status === "LIVE_CONNECTOR_FAILED") return "Evidence connector failed";
  if (status === "LIVE_INVALID_ANSWER") return "AI returned no usable answer";
  if (status === "LIVE_PROVIDER_ERROR" || status === "LIVE_ERROR") return "AI provider error";
  if (status === "SKIP_EXTERNAL") return "External provider not called";
  if (status === "CONNECTED") return "Connector reachable";
  if (status === "SUCCESS" || status === "COMPLETED" || status === "PASS" || status === "PASSED") return "Passed";
  if (status === "FAILED" || status === "ERROR" || status === "FAIL") return "Failed";
  if (status === "QUEUED" || status === "RUNNING" || status === "MONITORING") return "In progress";
  if (status === "NOT_RUN") return "Not run";
  if (status === "STALE") return "Stale";
  return value ? String(value).replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase()) : "Not available";
}

function friendlyMode(value?: string | null): string {
  const mode = String(value ?? "").toUpperCase();
  if (mode.includes("LIVE_OPENAI")) return "Live AI answer with verified tools";
  if (mode === "AI_UNAVAILABLE_EVIDENCE_ONLY") return "Evidence-only fallback (AI unavailable)";
  if (mode === "VERIFIED_TOOL_RESPONSE") return "Evidence-backed connector result";
  if (mode === "DETERMINISTIC") return "Deterministic evidence result";
  return value ? String(value).replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase()) : "Evidence-backed answer";
}

function agentErrorMessage(value?: string | Record<string, unknown>): string {
  if (typeof value === "string") return value;
  if (value && typeof value.message === "string") return value.message;
  return "The configured AI provider could not complete the request.";
}

function agentFailure(agent?: AgentResponse["agent"]): { heading: string; detail: string; nextAction: string } | null {
  const kind = String(agent?.failure_kind ?? agent?.status ?? "").replace(/^LIVE_/, "").toUpperCase();
  if (kind === "QUERY_LIMIT_REACHED") return {
    heading: "AI stopped at the evidence-query limit",
    detail: "It collected the allowed evidence but still requested another query. No answer was accepted.",
    nextAction: "Ask a narrower question, or select one asset or run so the answer can be resolved within the limit.",
  };
  if (kind === "PROVIDER_TIMEOUT") return {
    heading: "AI provider timed out",
    detail: "The provider did not finish within the bounded request deadline. Collected evidence is still available.",
    nextAction: "Retry the same scoped question. If it repeats, inspect provider latency and timeout settings.",
  };
  if (kind === "CONNECTOR_FAILED") return {
    heading: "Evidence connector failed",
    detail: "The AI could not complete its answer because one or more requested evidence queries failed.",
    nextAction: "Open the failed evidence, resolve that connector issue, then retry the same scoped question.",
  };
  if (kind === "INVALID_ANSWER") return {
    heading: "AI returned no usable answer",
    detail: "The provider completed the request without a valid final response. Collected evidence is still available.",
    nextAction: "Retry the same scoped question. If it repeats, inspect the provider response details.",
  };
  if (kind === "PROVIDER_ERROR" || kind === "ERROR") return {
    heading: "AI provider could not complete the request",
    detail: "Collected evidence is still available, but no AI answer was accepted.",
    nextAction: "Retry the same scoped question. If it repeats, inspect the provider error details.",
  };
  return null;
}

function compactNarrative(value: string | undefined, fallback: string): string {
  if (!value || /evidence collection completed with status/i.test(value)) return fallback;
  const sentence = value.trim().split(/(?<=[.!?])\s+/).slice(0, 2).join(" ");
  return sentence.length > 360 ? `${sentence.slice(0, 357).trimEnd()}…` : sentence;
}

function isGenericEvidenceAnswer(value?: string): boolean {
  return !value || /evidence collection completed with status|review the supporting facts/i.test(value);
}

function looksLikeExecutionRequest(value: string): boolean {
  return /^(run|execute|start|trigger|refresh|load|rerun|retry)\b/i.test(value.trim());
}

function evidenceHref(value?: string | null): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  return value.replace(/^\/api\/v1\/evidence\//, "/evidence/");
}

function usageLabel(usage?: AgentUsage | null): string {
  if (!usage) return "Not reported";
  const input = Number(usage.input_tokens ?? 0);
  const output = Number(usage.output_tokens ?? 0);
  const total = input + output;
  return total > 0 ? `${total.toLocaleString()} tokens (${input.toLocaleString()} in · ${output.toLocaleString()} out)` : "0 tokens reported";
}

function AskHistory({ items }: { items: AgentHistoryItem[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = items.find((item, index) => (item.invocation_id ?? `${item.question}-${index}`) === selectedId);
  const completeItems = items.filter((item) => Boolean(item.answer) || Boolean(item.error) || typeof item.latency_ms === "number");
  useEffect(() => {
    if (!selectedId) return;
    window.requestAnimationFrame(() => document.getElementById("ask-ai-history-detail-heading")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [selectedId]);
  return <section className={styles.panel} aria-labelledby="ask-ai-history-heading">
    <header className={styles.panelHead}><div><h2 id="ask-ai-history-heading">Ask AI history</h2><p>Select a question to inspect its complete response and supporting details.</p></div><span>{completeItems.length} complete</span></header>
    {items.length ? <div className={local.historyList}>{items.map((item, index) => {
      const itemId = item.invocation_id ?? `${item.question}-${index}`;
      const status = String(item.status ?? "").toUpperCase();
      const failed = Boolean(item.error) || (status.startsWith("LIVE_") && status !== "LIVE_RESPONSE");
      return <button type="button" className={`${local.historyItem} ${selectedId === itemId ? local.historyItemSelected : ""}`} key={itemId} onClick={() => setSelectedId(itemId)} onDoubleClick={() => setSelectedId(itemId)} data-selected={selectedId === itemId ? "true" : undefined} aria-label={`Open response: ${item.question || "Question not retained"}`}>
        <span className={local.historyEntryMain}><span><span className={styles.eyebrow}>{humanStatus(item.status)}</span><strong>{item.question || "Question not retained"}</strong><small>{formatDateTime(item.created_at)}</small></span><span className={failed ? styles.answerWarn : styles.answerGood}>{failed ? "Needs attention" : item.answer ? "Recorded" : "Older entry"}</span></span>
        <span className={local.historyMeta}><span>{item.provider ?? "Evidence only"}{item.model ? ` · ${item.model}` : ""}</span><span>{typeof item.latency_ms === "number" ? `${Math.round(item.latency_ms).toLocaleString()} ms` : "Latency not recorded"}</span><span>{usageLabel(item.usage)}</span><span>{Array.isArray(item.evidence_references) ? `${item.evidence_references.length} evidence records` : "No evidence count"}</span></span>
      </button>;
    })}</div> : <div className={local.historyEmpty}><strong>No Ask AI questions saved yet</strong><p>The next question will retain its answer, model, usage, latency, scope, and evidence references.</p></div>}
    {selected ? <HistoryViewer item={selected} /> : items.length ? <div className={local.historyPrompt}>Select a question above to open its full response.</div> : null}
  </section>;
}

function HistoryViewer({ item }: { item: AgentHistoryItem }) {
  const scope = item.scope ?? {};
  const status = String(item.status ?? "").toUpperCase();
  const failed = Boolean(item.error) || (status.startsWith("LIVE_") && status !== "LIVE_RESPONSE");
  return <section className={local.historyViewer} aria-labelledby="ask-ai-history-detail-heading">
    <header className={local.historyViewerHeader}><div><span className={styles.eyebrow}>SELECTED RESPONSE</span><h2 id="ask-ai-history-detail-heading">{item.question || "Question not retained"}</h2><small>{formatDateTime(item.created_at)}</small></div><span className={failed ? styles.answerWarn : styles.answerGood}>{humanStatus(item.status)}</span></header>
    <div className={local.historyViewerMeta}><span><strong>Provider</strong>{item.provider ?? "Evidence only"}{item.model ? ` · ${item.model}` : ""}</span><span><strong>Latency</strong>{typeof item.latency_ms === "number" ? `${Math.round(item.latency_ms).toLocaleString()} ms` : "Not recorded"}</span><span><strong>Usage</strong>{usageLabel(item.usage)}</span></div>
    <section className={local.historyResponse}><h3>{failed ? "Result" : "Response"}</h3><p>{item.answer || (failed ? "No final AI answer was recorded." : "This older entry did not retain a complete answer and cannot be reconstructed.")}</p>{item.error ? <p className={styles.warningText}>{agentErrorMessage(item.error)}</p> : null}</section>
    <div className={local.historyViewerGrid}><section><h3>Scope</h3><div className={styles.summaryList}><div className={styles.summaryRow}><span>Project / environment<small>{scope.project_id ?? "Not recorded"} · {scope.environment ?? "Not recorded"}</small></span><strong>Scoped</strong></div>{scope.selected_asset ? <div className={styles.summaryRow}><span>Asset<small>{scope.selected_asset}</small></span><strong>Selected</strong></div> : null}{scope.run_id ? <div className={styles.summaryRow}><span>Run<small>{scope.run_id}</small></span><strong>Selected</strong></div> : null}</div></section><section><h3>Evidence and tools</h3><div className={styles.summaryList}>{item.evidence_references?.length ? item.evidence_references.map((reference) => <div className={styles.summaryRow} key={reference}><span>Evidence<small>{reference}</small></span><strong>Linked</strong></div>) : <div className={styles.summaryRow}><span>No evidence references retained</span><strong>Not available</strong></div>}</div><div className={styles.capabilityList}>{item.tools_used?.length ? item.tools_used.map((tool) => <span className={styles.capability} key={tool}>{tool}</span>) : <span className={styles.muted}>No AI tool calls recorded</span>}</div></section></div>
  </section>;
}

function readableResult(response: AgentResponse): { headline: string; detail: string; facts: Array<{ label: string; value: string; tone?: "good" | "warn" | "neutral" }>; unknowns: string[]; nextAction: string; mode: string; updated: string } {
  const result = resultRecord(response.result);
  const dags = objectList(result.dags) as AirflowDag[];
  const normalizedQuestion = String((response as AgentResponse & { question?: string }).question ?? "").toLowerCase();
  const dag = dags.find((item) => item.dag_id && normalizedQuestion.includes(item.dag_id.toLowerCase())) ?? (dags.length === 1 ? dags[0] : undefined);
  const phases = objectList(result.orchestration?.phases);
  const runs = phases.flatMap((phase) => objectList(phase.dags) as OrchestrationRun[]).filter((item) => !dag?.dag_id || item.dag_id === dag.dag_id);
  const latestRun = [...runs].sort((a, b) => String(b.ended_at ?? b.started_at ?? "").localeCompare(String(a.ended_at ?? a.started_at ?? "")))[0];
  const taskInstanceFailures = (Array.isArray(result.task_instances) ? result.task_instances : []).filter((item) => item && typeof item === "object" && String((item as Record<string, unknown>).state ?? "").toLowerCase() === "failed").length;
  const failedTaskCount = Math.max(taskInstanceFailures, (Array.isArray(result.failed_tasks) ? result.failed_tasks : []).length, (Array.isArray(result.task_instance_errors) ? result.task_instance_errors : []).length);
  const status = latestRun?.status ?? result.status;
  const freshness = result.freshness ?? "";
  const targetName = dag?.dag_id ?? "the requested workflow";
  const modelAnswer = isGenericEvidenceAnswer(response.answer) ? "" : response.answer;
  const agentOutcome = String(response.agent?.status ?? "").toUpperCase();
  const liveExplanation = agentOutcome === "LIVE_RESPONSE" && Boolean(modelAnswer);
  const directAnswer = liveExplanation ? "" : modelAnswer;
  const failure = agentFailure(response.agent);
  const evidenceOnly = ["VERIFIED_TOOL_RESPONSE", "TOOL_EVIDENCE_ONLY"].includes(agentOutcome)
    || String(response.evidence?.mode ?? "").toLowerCase() === "evidence_only";
  const executionRequest = result.request_type === "execution"
    || /^(can you\s+)?(run|execute|start|trigger|refresh|load|rerun|retry)\b/i.test(normalizedQuestion);
  const headline = executionRequest
    ? "This is an execution request, not an explanation request."
    : dag
    ? `${targetName} is ${dag.is_paused ? "paused" : "active"}.`
    : liveExplanation
      ? "AI explanation completed."
      : directAnswer
        ? "Evidence collected."
      : failure
        ? failure.heading
      : evidenceOnly
        ? "Evidence was collected; AI review was not run."
        : `Evidence collection is ${humanStatus(result.status)}.`;
  const detail = executionRequest
    ? "Ask AI does not submit jobs. Open Run jobs to select the exact scope, preview it, and approve it before execution."
    : dag && latestRun
    ? `Its latest recorded run is ${humanStatus(status).toLowerCase()}${latestRun.started_at ? `, starting ${formatDateTime(latestRun.started_at)}` : ""} (${formatDuration(latestRun.started_at, latestRun.ended_at)}).`
    : liveExplanation
      ? compactNarrative(modelAnswer, "The available connector evidence is summarized below.")
      : directAnswer
        ? directAnswer
      : failure
        ? failure.detail
      : evidenceOnly
        ? "The selected connectors returned scoped evidence. No model-generated explanation was produced for this request."
        : "No model-generated explanation was returned. The available scoped evidence is summarized below.";
  const facts: Array<{ label: string; value: string; tone?: "good" | "warn" | "neutral" }> = [];
  if (dag) facts.push({ label: "Schedule", value: dag.timetable_description ?? dag.timetable_summary ?? "Not scheduled", tone: "neutral" });
  if (latestRun) facts.push({ label: "Latest run", value: `${humanStatus(status)}${latestRun.run_id ? ` · ${latestRun.run_id}` : ""}`, tone: status === "SUCCESS" ? "good" : status === "FAILED" ? "warn" : "neutral" });
  if (failedTaskCount) facts.push({ label: "Historical task failures", value: `${failedTaskCount} recorded failure${failedTaskCount === 1 ? "" : "s"}`, tone: "warn" });
  if (result.orchestration?.runtime_runs_observed !== undefined) facts.push({ label: "Runtime observations", value: String(result.orchestration.runtime_runs_observed), tone: "neutral" });
  if (freshness) facts.push({ label: "Evidence freshness", value: humanStatus(freshness), tone: freshness.toUpperCase() === "STALE" ? "warn" : "good" });
  const unknowns = stringList(response.uncertainty).map((item) => /AI verification was not invoked/i.test(item)
    ? "This is a connector-evidence summary, not a separate AI review or approval."
    : /deterministic or connector evidence/i.test(item)
      ? "The answer summarizes observed connector evidence; it does not certify data quality."
      : item);
  if (dag) unknowns.unshift("This confirms Airflow runtime metadata only; it does not prove Snowflake loads, dbt completion, or data-quality results.");
  if (freshness.toUpperCase() === "STALE") unknowns.push(`The runtime snapshot may be stale. Last refresh: ${formatDateTime(result.last_refreshed)}.`);
  const nextAction = executionRequest
    ? "Open Run jobs, select one exact operation, then preview and approve the resulting plan."
    : failure
      ? failure.nextAction
    : directAnswer
      ? response.next_action ?? "Use the exact operation name in Run jobs if you want to prepare an execution request."
    : evidenceOnly
    ? "Ask a scoped factual question again when you want an AI interpretation; connector evidence alone is not an AI review."
    : String(latestRun?.status ?? "").toUpperCase() === "SUCCESS"
    ? "Open the exact run evidence to inspect task results, then verify downstream Snowflake/dbt steps separately."
    : String(latestRun?.status ?? "").toUpperCase() === "FAILED"
      ? "Open the exact failed run and inspect the failed task log before retrying."
      : response.next_action ?? "Review the exact evidence before taking action.";
  return { headline, detail, facts, unknowns: Array.from(new Set(unknowns)), nextAction, mode: friendlyMode(response.evidence?.mode ?? response.agent?.status), updated: formatDateTime(response.evidence?.timestamp ?? result.last_refreshed) };
}

export default function AgentPage() {
  const [agentStatus, setAgentStatus] = useState<Record<string, unknown>>({});
  const [question, setQuestion] = useState("");
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [projectId, setProjectId] = useState("data-quality-testing-beta");
  const [environment, setEnvironment] = useState("development");
  const [selectedAsset, setSelectedAsset] = useState("");
  const [runId, setRunId] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"ask" | "history">("ask");

  const loadAgentStatus = () => fetch(scopedApiUrl("/api/agent"), { cache: "no-store" })
    .then((item) => item.json())
    .then(setAgentStatus)
    .catch(() => setAgentStatus({ status: "ERROR" }));
  useEffect(() => {
    const workspace = currentWorkspaceParams();
    setProjectId(workspace.get("project_id") || "data-quality-testing-beta");
    setEnvironment(workspace.get("environment") || "development");
    void loadAgentStatus();
  }, []);

  const ask = async () => {
    setBusy(true);
    setResponse(null);
    try {
      const item = await fetch(scopedApiUrl("/api/agent"), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, project_id: projectId, environment, selected_asset: selectedAsset || null, run_id: runId || null }),
      });
      const value = await item.json() as AgentResponse;
      if (!item.ok) throw new Error(value.error || "Agent query failed");
      setResponse({ ...value, question });
      void loadAgentStatus();
    } catch (error) {
      setResponse({ error: error instanceof Error ? error.message : "Agent query failed" });
    } finally {
      setBusy(false);
    }
  };

  const toolsUsed = Array.from(new Set(stringList(response?.evidence?.tools_used ?? response?.tools_used)));
  const dataSources = Array.from(new Set(stringList(response?.evidence?.data_sources ?? response?.data_sources)));
  const supportingFacts = objectList(response?.supporting_facts);
  const evidenceLinks = objectList(response?.evidence_links) as EvidenceLink[];
  const readable = response && !response.error ? readableResult(response) : null;
  const responseResult = resultRecord(response?.result);
  const requiresQualityScope = responseResult.quality_scope === "REQUIRED";
  const executionRequest = looksLikeExecutionRequest(question);
  const assetOptions = (Array.isArray(agentStatus.assets) ? agentStatus.assets : Array.isArray(agentStatus.catalog) ? agentStatus.catalog : []).map((item) => typeof item === "string" ? item : item && typeof item === "object" ? String((item as Record<string, unknown>).qualified_name ?? (item as Record<string, unknown>).name ?? "") : "").filter(Boolean);
  const runOptions = (Array.isArray(agentStatus.runs) ? agentStatus.runs : []).map((item) => typeof item === "string" ? item : item && typeof item === "object" ? String((item as Record<string, unknown>).run_id ?? "") : "").filter(Boolean);
  const historyItems = (Array.isArray(agentStatus.agent_history) ? agentStatus.agent_history : []).filter((item): item is AgentHistoryItem => !!item && typeof item === "object");
  return <DraftShell active="agent">
    <header className={`${styles.topbar} ${local.pageHeader}`}>
      <div>
        <span className={styles.eyebrow}>ASK AI / EVIDENCE-BACKED ANSWERS</span>
        <h1>Ask AI</h1>
        <p>Ask about the selected project, asset, or run. Answers cite only the scope below.</p>
      </div>
    </header>
    <div className={local.viewTabs} role="tablist" aria-label="Ask AI views"><button role="tab" aria-selected={view === "ask"} className={view === "ask" ? local.viewTabActive : local.viewTab} onClick={() => setView("ask")}>Ask AI</button><button role="tab" aria-selected={view === "history"} className={view === "history" ? local.viewTabActive : local.viewTab} onClick={() => setView("history")}>History <span>{historyItems.length}</span></button></div>
    <div className={styles.askAiLayout}>
      {view === "history" ? <AskHistory items={historyItems} /> : <section className={styles.panel}>
        <header className={styles.panelHead}>
          <div><h2>Question</h2><p>Choose the context first, then ask one clear question.</p></div>
        </header>
        <div className={styles.scopeGrid}>
          <label className={styles.field}>Current project<input value={projectId} readOnly aria-readonly="true" /></label>
          <label className={styles.field}>Environment<select value={environment} onChange={(event) => setEnvironment(event.target.value)}><option value="development">Development</option><option value="staging">Staging</option><option value="production">Production</option></select></label>
          <label className={styles.field}>Asset context<input list="ask-ai-assets" value={selectedAsset} placeholder="Choose or enter an asset" onChange={(event) => setSelectedAsset(event.target.value)} /><datalist id="ask-ai-assets">{assetOptions.map((item) => <option key={item} value={item} />)}</datalist></label>
          <label className={styles.field}>Run context<input list="ask-ai-runs" value={runId} placeholder="Optional persisted run" onChange={(event) => setRunId(event.target.value)} /><datalist id="ask-ai-runs">{runOptions.map((item) => <option key={item} value={item} />)}</datalist></label>
        </div>
        <label className={[styles.field, styles.wide].join(" ")}>
          Question
          <textarea value={question} placeholder="Ask a question about this project, selected asset, or run" onChange={(event) => setQuestion(event.target.value)} />
        </label>
        {executionRequest && <div className={styles.executionNotice} role="status"><div><strong>Execution request detected</strong><p>Ask AI can explain the request, but it will not run a job from this page. Review scope, dependencies, and approval in Run jobs.</p></div><a href={scopedApiUrl("/actions")}>Open Run jobs →</a></div>}
        <div className={styles.toolbar}>
          <button className={styles.primary} disabled={busy || !question.trim()} onClick={() => void ask()}>
            {busy ? "Thinking…" : "Ask AI"}
          </button>
        </div>
        {response?.error && <div className={styles.dangerStrip} role="alert">{response.error}</div>}
        {response?.agent?.error && <div className={styles.dangerStrip} role="alert">{agentFailure(response.agent)?.heading ?? "AI provider error"}: {agentErrorMessage(response.agent.error)}</div>}
        {response && !response.error && readable && <div className={styles.sectionStack} aria-live="polite">
          <h3>Answer</h3>
          <section className={styles.answerCard}>
            <div className={styles.answerHeader}><span className={styles.answerEyebrow}>CURRENT STATUS</span><span className={styles.answerStatus}>{humanStatus(requiresQualityScope ? responseResult.status : response.agent?.status ?? responseResult.status)}</span></div>
            <h2>{readable.headline}</h2>
            <p>{readable.detail}</p>
            <div className={styles.answerFacts}>{readable.facts.map((item) => <div className={styles.answerFact} key={item.label}><small>{item.label}</small><strong className={item.tone === "warn" ? styles.answerWarn : item.tone === "good" ? styles.answerGood : ""}>{item.value}</strong></div>)}</div>
            <div className={styles.answerMeta}>Based on exact connector evidence · updated {readable.updated}</div>
          </section>
          <details className={local.answerDetails}><summary>Evidence and supporting records <span>{evidenceLinks.length} linked record{evidenceLinks.length === 1 ? "" : "s"}</span></summary><div className={local.detailContent}><div className={styles.summaryList}>{[...(readable.facts.map((item) => ({ fact: `${item.label}: ${item.value}`, status: item.tone === "warn" ? "Attention" : "Observed" }))), ...supportingFacts.map((item) => ({ fact: typeof item.fact === "string" ? item.fact : "Observed evidence", status: typeof item.status === "string" ? humanStatus(item.status) : "Observed" }))].map((item, index) => <div className={styles.summaryRow} key={`${item.fact}-${index}`}><span>{item.fact}</span><strong>{item.status}</strong></div>)}</div><div className={styles.summaryList}>{evidenceLinks.length ? evidenceLinks.map((item, index) => <div className={styles.summaryRow} key={`${typeof item.reference === "string" ? item.reference : item.type ?? "evidence"}-${index}`}><span>{typeof item.label === "string" ? item.label : "Evidence record"}<small>{typeof item.type === "string" ? item.type : "evidence"} · {typeof item.reference === "string" ? item.reference : "No reference"}</small></span><span className={styles.evidenceActions}><strong>{humanStatus(item.status)}</strong>{evidenceHref(item.href) ? <a href={evidenceHref(item.href)!}>Open record</a> : null}</span></div>) : <div className={styles.summaryRow}><span>No evidence links returned</span><strong>Not available</strong></div>}</div></div></details>
          <section><h3>Uncertainty</h3><div className={styles.infoStrip}><span>i</span><div>{(readable.unknowns.length ? readable.unknowns : ["No additional uncertainty was returned."]).map((item, index) => <p key={`${item}-${index}`}>{item}</p>)}</div></div></section>
          <section><h3>Next action</h3><div className={styles.callout}><strong>{readable.nextAction}</strong></div></section>
          <details className={local.answerDetails}><summary>Technical details</summary><div className={local.detailContent}>
          <section><h3>Interpretation mode</h3><div className={styles.summaryRow}><span>{readable.mode}</span><strong>{readable.updated}</strong></div></section>
          {String(response.agent?.status ?? "").toUpperCase() === "LIVE_RESPONSE" && response.answer && !isGenericEvidenceAnswer(response.answer) && <section><h3>Full AI answer</h3><p className={styles.rawNarrative}>{response.answer}</p></section>}
          <section>
            <h3>Tools used</h3>
            <div className={styles.capabilityList}>{toolsUsed.length ? toolsUsed.map((item, index) =>
              <span className={styles.capability} key={`${item}-${index}`}>{item}</span>
            ) : <span className={styles.muted}>No tool calls recorded</span>}</div>
          </section>
          <section>
            <h3>Evidence sources</h3>
            <div className={styles.summaryList}>{dataSources.length ? dataSources.map((item, index) =>
              <div className={styles.summaryRow} key={`${item}-${index}`}><span>{item}</span><strong>OBSERVED</strong></div>
            ) : <div className={styles.summaryRow}><span>No evidence sources returned</span><strong>—</strong></div>}</div>
          </section>
            <details><summary>Structured result</summary><pre className={styles.codeViewer}><code>{JSON.stringify(response.result, null, 2)}</code></pre></details>
          </div></details>
        </div>}
      </section>}
    </div>
  </DraftShell>;
}
