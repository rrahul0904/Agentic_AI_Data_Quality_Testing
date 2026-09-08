"use client";

import { useEffect, useState } from "react";
import { getJson } from "../lib/api";

type TraceSummary = { trace_id: string; started_at: string; ended_at: string; event_count: number; error_count: number; tool_count: number; generation_count: number; session_id?: string | null };
type TraceReplay = { trace_id: string; mode: string; reexecuted: boolean; event_count: number; timeline: Array<Record<string, unknown>> };

export default function TraceConsole() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [replay, setReplay] = useState<TraceReplay | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getJson<{ traces: TraceSummary[] }>("/api/v1/traces?limit=50")
      .then((payload) => setTraces(payload.traces ?? []))
      .catch((cause) => setError(String(cause)));
  }, []);

  async function show(traceId: string) {
    try {
      const path = "/api/v1/traces/" + encodeURIComponent(traceId) + "/replay";
      setReplay(await getJson<TraceReplay>(path));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  return <section className="panel">
    <header className="panel-head"><div><p className="eyebrow">READ-ONLY EXECUTION EVIDENCE</p><h2>Trace replay</h2></div></header>
    {error && <div className="error-banner">{error}</div>}
    <div className="two-col equal">
      <div className="trace-list">
        {traces.map((item) => <button key={item.trace_id} className="trace-row" onClick={() => void show(item.trace_id)}>
          <strong>{item.trace_id}</strong>
          <span>{item.event_count} events · {item.tool_count} tools · {item.error_count} errors</span>
          <small>{item.started_at}</small>
        </button>)}
        {!traces.length && <p>No traces recorded yet.</p>}
      </div>
      <div className="trace-timeline">
        {!replay ? <p>Select a trace. Viewing a trace never re-executes tools.</p> : <>
          <div className="inline-summary"><span>{replay.event_count} events</span><span>{replay.mode}</span><span>reexecuted: {String(replay.reexecuted)}</span></div>
          {replay.timeline.map((step, index) => <article className="trace-step" key={String(step.event_id ?? index)}>
            <strong>{String(step.kind ?? "event")} · {String(step.name ?? "")}</strong>
            <span>{String(step.status ?? "")} · {String(step.duration_ms ?? "—")} ms</span>
            <pre>{JSON.stringify(step, null, 2)}</pre>
          </article>)}
        </>}
      </div>
    </div>
  </section>;
}
