"use client";

import type { Evidence } from "./types";

export default function EvidenceDrawer({ evidence, onClose }: { evidence: Evidence | null; onClose: () => void }) {
  if (!evidence) return null;
  return (
    <aside className="evidence-drawer" aria-label="Evidence details">
      <header><div><span>{evidence.tier} · {evidence.kind.replaceAll("_", " ")}</span><h2>{evidence.summary}</h2></div><button onClick={onClose} aria-label="Close evidence drawer">×</button></header>
      <dl>
        <div><dt>Source</dt><dd>{evidence.source}</dd></div>
        <div><dt>Captured</dt><dd>{new Date(evidence.created_at).toLocaleString()}</dd></div>
        <div><dt>Evidence ID</dt><dd className="mono">{evidence.evidence_id}</dd></div>
      </dl>
      <section><span>Normalized evidence</span><pre>{JSON.stringify(evidence.payload, null, 2)}</pre></section>
      {evidence.correlation && Object.keys(evidence.correlation).length > 0 && <section><span>Correlation</span><pre>{JSON.stringify(evidence.correlation, null, 2)}</pre></section>}
      <p>Database and log content is treated as untrusted evidence and never as agent instructions.</p>
    </aside>
  );
}
