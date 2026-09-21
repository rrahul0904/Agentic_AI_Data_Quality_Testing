"use client";

import { useEffect, useState } from "react";
import DraftShell from "../DraftShell";
import styles from "../workflow.module.css";
import { currentWorkspaceParams, scopedApiUrl } from "../../lib/client-workspace";

type EvidenceLink = { label?: string; type?: string; status?: string; reference?: string; href?: string | null };
type AirflowDag = { dag_id?: string; is_paused?: boolean; timetable_description?: string; timetable_summary?: string };
type OrchestrationRun = { dag_id?: string; status?: string; run_id?: string | null; started_at?: string | null; ended_at?: string | null };
type AgentResult = {
  status?: string;
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
  agent?: { status?: string; error?: string; provider?: string; model?: string | null };
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
  if (status === "LIVE_ERROR") return "AI explanation unavailable";
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
  if (mode === "VERIFIED_TOOL_RESPONSE") return "Evidence-backed connector result";
  if (mode === "DETERMINISTIC") return "Deterministic evidence result";
  return value ? String(value).replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase()) : "Evidence-backed answer";
}

function compactNarrative(value: string | undefined, fallback: string): string {
  if (!value || /evidence collection completed with status/i.test(value)) return fallback;
  const sentence = value.trim().split(/(?<=[.!?])\s+/).slice(0, 2).join(" ");
  return sentence.length > 360 ? `${sentence.slice(0, 357).trimEnd()}…` : sentence;
}

function looksLikeExecutionRequest(value: string): boolean {
  return /^(run|execute|start|trigger|refresh|load|rerun|retry)\b/i.test(value.trim());
}

function evidenceHref(value?: string | null): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  return value.replace(/^\/api\/v1\/evidence\//, "/evidence/");
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
  const headline = dag
    ? `${targetName} is ${dag.is_paused ? "paused" : "active"}.`
    : compactNarrative(response.question, `Evidence collection is ${humanStatus(result.status)}.`);
  const detail = dag && latestRun
    ? `Its latest recorded run is ${humanStatus(status).toLowerCase()}${latestRun.started_at ? `, starting ${formatDateTime(latestRun.started_at)}` : ""} (${formatDuration(latestRun.started_at, latestRun.ended_at)}).`
    : compactNarrative(response.question, "The available connector evidence is summarized below.");
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
  const nextAction = String(latestRun?.status ?? "").toUpperCase() === "SUCCESS"
    ? "Open the exact run evidence to inspect task results, then verify downstream Snowflake/dbt steps separately."
    : String(latestRun?.status ?? "").toUpperCase() === "FAILED"
      ? "Open the exact failed run and inspect the failed task log before retrying."
      : response.next_action ?? "Review the exact evidence before taking action.";
  return { headline, detail, facts, unknowns: Array.from(new Set(unknowns)), nextAction, mode: friendlyMode(response.evidence?.mode ?? response.agent?.status), updated: formatDateTime(response.evidence?.timestamp ?? result.last_refreshed) };
}

export default function AgentPage() {
  const [agentStatus, setAgentStatus] = useState<Record<string, unknown>>({});
  const [question, setQuestion] = useState("What is the current quality status and which evidence supports it?");
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [projectId, setProjectId] = useState("data-quality-testing-beta");
  const [environment, setEnvironment] = useState("development");
  const [selectedAsset, setSelectedAsset] = useState("");
  const [runId, setRunId] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const workspace = currentWorkspaceParams();
    setProjectId(workspace.get("project_id") || "data-quality-testing-beta");
    setEnvironment(workspace.get("environment") || "development");
    fetch(scopedApiUrl("/api/agent"), { cache: "no-store" })
      .then((item) => item.json())
      .then(setAgentStatus)
      .catch(() => setAgentStatus({ status: "ERROR" }));
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
  const executionRequest = looksLikeExecutionRequest(question);
  const assetOptions = (Array.isArray(agentStatus.assets) ? agentStatus.assets : Array.isArray(agentStatus.catalog) ? agentStatus.catalog : []).map((item) => typeof item === "string" ? item : item && typeof item === "object" ? String((item as Record<string, unknown>).qualified_name ?? (item as Record<string, unknown>).name ?? "") : "").filter(Boolean);
  const runOptions = (Array.isArray(agentStatus.runs) ? agentStatus.runs : []).map((item) => typeof item === "string" ? item : item && typeof item === "object" ? String((item as Record<string, unknown>).run_id ?? "") : "").filter(Boolean);
  return <DraftShell active="agent">
    <header className={styles.topbar}>
      <div>
        <span className={styles.eyebrow}>ASK AI / EVIDENCE-BACKED ANSWERS</span>
        <h1>Ask AI</h1>
        <p>Ask questions about this project, its systems, assets, runs, and quality evidence. Execution is reviewed separately in Run jobs.</p>
      </div>
    </header>
    <div className={styles.askAiLayout}>
      <section className={styles.panel}>
        <header className={styles.panelHead}>
          <div><h2>Question</h2><p>Ask about actual assets, executions, failures, lineage, or connection state.</p></div>
        </header>
        <div className={styles.scopeGrid}>
          <label className={styles.field}>Current project<input value={projectId} readOnly aria-readonly="true" /></label>
          <label className={styles.field}>Environment<select value={environment} onChange={(event) => setEnvironment(event.target.value)}><option value="development">Development</option><option value="staging">Staging</option><option value="production">Production</option></select></label>
          <label className={styles.field}>Asset context<input list="ask-ai-assets" value={selectedAsset} placeholder="Choose or enter an asset" onChange={(event) => setSelectedAsset(event.target.value)} /><datalist id="ask-ai-assets">{assetOptions.map((item) => <option key={item} value={item} />)}</datalist></label>
          <label className={styles.field}>Run context<input list="ask-ai-runs" value={runId} placeholder="Optional persisted run" onChange={(event) => setRunId(event.target.value)} /><datalist id="ask-ai-runs">{runOptions.map((item) => <option key={item} value={item} />)}</datalist></label>
        </div>
        <label className={[styles.field, styles.wide].join(" ")}>
          Question
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} />
        </label>
        {executionRequest && <div className={styles.executionNotice} role="status"><div><strong>Execution request detected</strong><p>Ask AI can explain the request, but it will not run a job from this page. Review scope, dependencies, and approval in Run jobs.</p></div><a href={scopedApiUrl("/actions")}>Open Run jobs →</a></div>}
        <div className={styles.toolbar}>
          <button className={styles.primary} disabled={busy || !question.trim()} onClick={() => void ask()}>
            {busy ? "Thinking…" : "Ask AI"}
          </button>
        </div>
        {response?.error && <div className={styles.dangerStrip}>{response.error}</div>}
        {response?.agent?.error && <div className={styles.dangerStrip}>Live agent unavailable: {response.agent.error}</div>}
        {response && !response.error && readable && <div className={styles.sectionStack}>
          <h3>Answer</h3>
          <section className={styles.answerCard}>
            <div className={styles.answerHeader}><span className={styles.answerEyebrow}>CURRENT STATUS</span><span className={styles.answerStatus}>{humanStatus(resultRecord(response.result).status ?? response.agent?.status)}</span></div>
            <h2>{readable.headline}</h2>
            <p>{readable.detail}</p>
            <div className={styles.answerFacts}>{readable.facts.map((item) => <div className={styles.answerFact} key={item.label}><small>{item.label}</small><strong className={item.tone === "warn" ? styles.answerWarn : item.tone === "good" ? styles.answerGood : ""}>{item.value}</strong></div>)}</div>
            <div className={styles.answerMeta}>Based on exact connector evidence · updated {readable.updated}</div>
          </section>
          <section><h3>Evidence</h3><div className={styles.summaryList}>{[...(readable.facts.map((item) => ({ fact: `${item.label}: ${item.value}`, status: item.tone === "warn" ? "ATTENTION" : "OBSERVED" }))), ...supportingFacts.map((item) => ({ fact: typeof item.fact === "string" ? item.fact : "Observed evidence", status: typeof item.status === "string" ? item.status : "OBSERVED" }))].map((item, index) => <div className={styles.summaryRow} key={`${item.fact}-${index}`}><span>{item.fact}</span><strong>{item.status}</strong></div>)}</div><div className={styles.summaryList}>{evidenceLinks.length ? evidenceLinks.map((item, index) => <div className={styles.summaryRow} key={`${typeof item.reference === "string" ? item.reference : item.type ?? "evidence"}-${index}`}><span>{typeof item.label === "string" ? item.label : "Evidence record"}<small>{typeof item.type === "string" ? item.type : "evidence"} · {typeof item.reference === "string" ? item.reference : "No reference"}</small></span><span className={styles.evidenceActions}><strong>{typeof item.status === "string" ? item.status : "not checked"}</strong>{evidenceHref(item.href) ? <a href={evidenceHref(item.href)!}>Open</a> : null}</span></div>) : <div className={styles.summaryRow}><span>No evidence links returned</span><strong>—</strong></div>}</div></section>
          <section><h3>Uncertainty</h3><div className={styles.infoStrip}><span>i</span><div>{(readable.unknowns.length ? readable.unknowns : ["No additional uncertainty was returned."]).map((item, index) => <p key={`${item}-${index}`}>{item}</p>)}</div></div></section>
          <section><h3>Next action</h3><div className={styles.callout}><strong>{readable.nextAction}</strong></div></section>
          <details><summary>Technical evidence</summary>
          <section><h3>Interpretation mode</h3><div className={styles.summaryRow}><span>{readable.mode}</span><strong>{readable.updated}</strong></div></section>
          {response.answer && !/evidence collection completed with status/i.test(response.answer) && <section><h3>Full AI answer</h3><p className={styles.rawNarrative}>{response.answer}</p></section>}
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
          </details>
        </div>}
      </section>
    </div>
  </DraftShell>;
}
