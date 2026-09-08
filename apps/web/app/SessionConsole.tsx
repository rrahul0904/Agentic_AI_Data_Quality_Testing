"use client";

import { useEffect, useState } from "react";
import { getJson } from "../lib/api";

type RuntimeSession = { session_id: string; title?: string | null; provider?: string | null; model?: string | null; created_at?: string; updated_at?: string };

export default function SessionConsole() {
  const [sessions, setSessions] = useState<RuntimeSession[]>([]);
  const [replay, setReplay] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getJson<{ sessions: RuntimeSession[] }>("/api/v1/runtime-sessions?limit=50")
      .then((payload) => setSessions(payload.sessions ?? []))
      .catch((cause) => setError(String(cause)));
  }, []);

  async function show(sessionId: string) {
    try {
      const path = "/api/v1/runtime-sessions/" + encodeURIComponent(sessionId) + "/replay";
      setReplay(await getJson<Record<string, unknown>>(path));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  return <section className="panel">
    <header className="panel-head"><div><p className="eyebrow">AGENT RUNTIME HISTORY</p><h2>Sessions</h2></div></header>
    {error && <div className="error-banner">{error}</div>}
    <div className="two-col equal">
      <div className="trace-list">
        {sessions.map((item) => <button key={item.session_id} className="trace-row" onClick={() => void show(item.session_id)}>
          <strong>{item.session_id}</strong>
          <span>{item.provider || "no provider"} · {item.model || "—"}</span>
          <small>{item.updated_at || item.created_at || ""}</small>
        </button>)}
        {!sessions.length && <p>No AgentRuntime sessions recorded yet.</p>}
      </div>
      <div className="trace-timeline">
        {!replay ? <p>Select a session to inspect conversation, tools, tokens, errors and final outcome.</p> : <pre>{JSON.stringify(replay, null, 2)}</pre>}
      </div>
    </div>
  </section>;
}
