"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { postJson } from "../../lib/api";
import { useLiveData } from "./use-live-data";

type IncidentSummary = {
  incident_id: string; title: string; state: string; question?: string; root_cause?: string | null;
  root_cause_confidence?: number; created_at: string; updated_at: string;
};

export default function InvestigationList() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const { data, error, loading, updatedAt, refresh } = useLiveData<{ incidents: IncidentSummary[] }>("/api/v1/investigations?limit=50", 5000);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setSubmitting(true); setSubmitError(null);
    try {
      const accepted = await postJson<{ incident_id: string }>("/api/v1/investigations", { question: question.trim() });
      router.push(`/investigations/${encodeURIComponent(accepted.incident_id)}`);
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : "ADE could not start the investigation");
    } finally { setSubmitting(false); }
  }

  return (
    <div className="investigation-index">
      <section className="workspace-heading"><div><span>INVESTIGATIONS</span><h1>Ask ADE what failed</h1><p>ADE follows runtime evidence to the earliest proven divergence.</p></div><div className="live-meta"><i />Live · {updatedAt ? `updated ${updatedAt.toLocaleTimeString()}` : "connecting"}</div></section>
      <form className="investigate-box" onSubmit={submit}>
        <label htmlFor="investigation-question">Ask ADE</label>
        <div><input id="investigation-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Why did ingest_reference_data fail?" autoComplete="off" /><button disabled={submitting || !question.trim()}>{submitting ? "Starting…" : "Investigate"}</button></div>
        <button type="button" className="prompt-suggestion" onClick={() => setQuestion("Why did ingest_reference_data fail?")}>Try: Why did ingest_reference_data fail?</button>
        {submitError && <p className="inline-error">{submitError}</p>}
      </form>
      <section className="list-section">
        <header><div><h2>Recent investigations</h2><p>Persisted incident history and current state</p></div><button onClick={() => void refresh()}>Refresh</button></header>
        {loading && !data ? <div className="state-panel"><span className="spinner" />Loading investigations…</div> : error && !data ? <div className="state-panel error"><strong>Investigations unavailable</strong><span>{error}</span></div> : !data?.incidents.length ? <div className="state-panel"><strong>No investigations yet</strong><span>Ask a question above to begin.</span></div> : (
          <div className="data-table"><table><thead><tr><th>Incident</th><th>Question / problem</th><th>State</th><th>Probable cause</th><th>Confidence</th><th>Updated</th></tr></thead><tbody>
            {data.incidents.map((item) => <tr key={item.incident_id}><td><Link href={`/investigations/${item.incident_id}`} className="mono table-link">{item.incident_id.slice(-12)}</Link></td><td><strong>{item.question || item.title}</strong><small>{item.question ? item.title : "Deterministic investigation"}</small></td><td><span className={`state-pill state-${item.state.toLowerCase()}`}>{item.state.replaceAll("_", " ")}</span></td><td>{item.root_cause?.replaceAll("_", " ") || "Investigating"}</td><td>{item.root_cause_confidence ? `${Math.round(item.root_cause_confidence * 100)}%` : "—"}</td><td>{new Date(item.updated_at).toLocaleString()}</td></tr>)}
          </tbody></table></div>
        )}
      </section>
    </div>
  );
}
