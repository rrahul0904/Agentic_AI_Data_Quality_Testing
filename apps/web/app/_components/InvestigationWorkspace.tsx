"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { postJson } from "../../lib/api";
import EvidenceDrawer from "./EvidenceDrawer";
import LifecycleView from "./Lifecycle";
import type { Evidence, Finding, Investigation } from "./types";
import { useLiveData } from "./use-live-data";

const TABS = ["Summary", "Timeline", "Hypotheses", "Evidence", "Impact", "Actions"] as const;
type Tab = typeof TABS[number];

function confidence(value: number) {
  if (value >= .9) return "HIGH";
  if (value >= .7) return "MEDIUM";
  return "LOW";
}

function findingTone(item: Finding) {
  if (item.classification.includes("ROOT_CAUSE")) return "critical";
  if (item.classification === "LATENT_DEFECT") return "warning";
  return "neutral";
}

export default function InvestigationWorkspace({ incidentId }: { incidentId: string }) {
  const [tab, setTab] = useState<Tab>("Summary");
  const [selected, setSelected] = useState<Evidence | null>(null);
  const [system, setSystem] = useState("ALL");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const { data: report, error, loading, updatedAt, refresh } = useLiveData<Investigation>(`/api/v1/investigations/${encodeURIComponent(incidentId)}`, 1800);

  const primary = report?.findings.find((item) => item.classification.includes("ROOT_CAUSE"));
  const secondary = report?.findings.filter((item) => !item.classification.includes("ROOT_CAUSE")) ?? [];
  const affectedSystems = [...new Set(["airflow", ...secondary.map((item) => item.domain)])];
  const lifecycle = report?.execution_lifecycles[0];
  const airflowHref = lifecycle?.dag_id && lifecycle.run_id
    ? `/airflow/dags/${encodeURIComponent(lifecycle.dag_id)}/runs/${encodeURIComponent(lifecycle.run_id)}?incident=${encodeURIComponent(incidentId)}`
    : "/airflow";

  const timeline = useMemo(() => {
    if (!report) return [];
    const transitions = report.transitions.map((item) => ({ id: item.transition_id, at: item.created_at, system: "ADE", label: item.reason, detail: item.to_state, evidence: null as Evidence | null }));
    const evidence = report.evidence.map((item) => ({ id: item.evidence_id, at: item.created_at, system: item.source.split(/[/.]/)[0].toUpperCase(), label: item.summary, detail: item.kind, evidence: item }));
    return [...transitions, ...evidence].filter((item) => system === "ALL" || item.system.includes(system)).sort((a, b) => a.at.localeCompare(b.at));
  }, [report, system]);

  async function act(kind: "approve" | "execute") {
    setActionBusy(true); setActionError(null);
    try {
      await postJson(`/api/v1/investigations/${encodeURIComponent(incidentId)}/${kind}`, kind === "approve" ? { approved_by: "ADE operator" } : {});
      await refresh();
    } catch (cause) { setActionError(cause instanceof Error ? cause.message : "Action failed"); }
    finally { setActionBusy(false); }
  }

  if (loading && !report) return <div className="full-state"><span className="spinner" /><strong>Opening investigation</strong><span>Loading persisted evidence and current agent progress…</span></div>;
  if (error && !report) return <div className="full-state error"><strong>Investigation unavailable</strong><span>{error}</span><Link href="/investigations">Return to investigations</Link></div>;
  if (!report) return null;

  return (
    <div className="investigation-workspace">
      <header className="incident-header">
        <div><div className="incident-kicker"><span className="mono">{report.incident_id.slice(-12)}</span><span className={`state-pill state-${report.state.toLowerCase()}`}>{report.state.replaceAll("_", " ")}</span>{!report.state.match(/RESOLVED|FAILED|BLOCKED/) && <span className="live-badge"><i />LIVE</span>}</div><h1>{report.question || report.scenario_id.replaceAll("_", " ")}</h1><p>{primary?.title || "ADE is collecting evidence and evaluating execution boundaries."}</p></div>
        <div className="incident-actions"><span>Updated {updatedAt?.toLocaleTimeString() || "now"}</span><button onClick={() => void refresh()}>Refresh</button><Link href={airflowHref} className="primary-link">Inspect Airflow</Link></div>
      </header>
      <nav className="workspace-tabs" aria-label="Investigation views">{TABS.map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}{item === "Evidence" && <span>{report.evidence.length}</span>}</button>)}</nav>

      {tab === "Summary" && <div className="investigation-split">
        <div className="investigation-primary">
          <section className="rca-hero">
            <div className="section-label">PRIMARY PROBABLE ROOT CAUSE <span>{confidence(report.root_cause_confidence)} · {Math.round(report.root_cause_confidence * 100)}%</span></div>
            <h2>{primary?.title || report.root_cause?.replaceAll("_", " ") || "Root cause not established"}</h2>
            <p>{primary?.description || "ADE has not gathered enough evidence to promote a hypothesis."}</p>
            {primary && <button className="evidence-link" onClick={() => setSelected(report.evidence.find((item) => primary.evidence_ids.includes(item.evidence_id)) || null)}>Inspect supporting evidence →</button>}
          </section>
          <section className="workspace-panel">
            <header><div><span className="section-label">FIRST DIVERGENCE</span><h2>{report.structured_first_divergence?.layer.replaceAll("_", " ") || "Not localized"}</h2></div>{report.structured_first_divergence?.proven && <span className="proven">PROVEN</span>}</header>
            {report.structured_first_divergence ? <div className="divergence-grid"><div><span>Expected</span><strong>{report.structured_first_divergence.expected_state}</strong></div><div className="divergence-arrow">≠</div><div><span>Observed</span><strong>{report.structured_first_divergence.observed_state}</strong></div></div> : <p className="empty-copy">Waiting for a proven boundary comparison.</p>}
            {lifecycle && <LifecycleView lifecycle={lifecycle} evidence={report.evidence} onEvidence={setSelected} />}
          </section>
          <section className="workspace-panel">
            <header><div><span className="section-label">FINDINGS</span><h2>Cause, defects, and consequences</h2></div></header>
            <div className="finding-stack">{secondary.length ? secondary.map((item) => <article key={item.finding_id} className={findingTone(item)}><div><span>{item.classification.replaceAll("_", " ")}</span><strong>{item.title}</strong></div><p>{item.description}</p><small>{item.relationship}</small></article>) : <p className="empty-copy">No secondary or unrelated findings.</p>}</div>
          </section>
        </div>
        <aside className="investigation-context">
          <section><span className="section-label">INVESTIGATION PROGRESS</span><div className="progress-list">{report.progress?.steps.length ? report.progress.steps.slice(-8).map((item) => <div key={item.id}><i /><span><strong>{item.state.replaceAll("_", " ")}</strong><small>{item.label}</small></span></div>) : <div><i className="active" /><span><strong>Detected</strong><small>Investigation is queued for evidence collection.</small></span></div>}</div></section>
          <section><span className="section-label">AFFECTED SYSTEMS</span><div className="system-list">{affectedSystems.map((systemName) => <span key={systemName}>{systemName.toUpperCase()}</span>)}</div></section>
          <section><span className="section-label">NEXT ACTION</span><p>{report.state === "AWAITING_APPROVAL" ? "Review the evidence-backed remediation proposal before approval." : "Continue collecting evidence at the current boundary."}</p><button onClick={() => setTab("Actions")}>Open actions</button></section>
        </aside>
      </div>}

      {tab === "Timeline" && <section className="workspace-panel tab-panel"><header><div><span className="section-label">EXECUTION + EVIDENCE</span><h2>Incident timeline</h2></div><select value={system} onChange={(event) => setSystem(event.target.value)}>{["ALL", "ADE", "AIRFLOW", "POSTGRES", "SNOWFLAKE", "DBT"].map((item) => <option key={item}>{item}</option>)}</select></header><div className="event-timeline">{timeline.map((item) => <button key={item.id} onClick={() => item.evidence && setSelected(item.evidence)} disabled={!item.evidence}><time>{new Date(item.at).toLocaleTimeString()}</time><span>{item.system}</span><div><strong>{item.label}</strong><small>{item.detail.replaceAll("_", " ")}</small></div></button>)}</div></section>}

      {tab === "Hypotheses" && <section className="workspace-panel tab-panel"><header><div><span className="section-label">EVOLVING REASONING</span><h2>Competing hypotheses</h2></div></header><div className="hypothesis-grid">{[...report.hypotheses].sort((a, b) => b.confidence - a.confidence).map((item, index) => <article key={item.hypothesis_id}><header><span>H{index + 1} · {item.domain.toUpperCase()}</span><span className={`state-pill state-${item.status.toLowerCase()}`}>{item.status}</span></header><h3>{item.statement}</h3><div className="confidence-bar"><i style={{ width: `${item.confidence * 100}%` }} /></div><strong>{Math.round(item.confidence * 100)}% confidence</strong><dl><div><dt>Supporting</dt><dd>{item.supporting_evidence_ids.length || "None"}</dd></div><div><dt>Contradicting</dt><dd>{item.contradictory_evidence_ids.length || "None"}</dd></div></dl><small>To prove: {item.prerequisites_to_prove?.join("; ") || "More direct evidence"}</small></article>)}</div></section>}

      {tab === "Evidence" && <section className="workspace-panel tab-panel"><header><div><span className="section-label">IMMUTABLE PROVENANCE</span><h2>Evidence bundle</h2></div></header><div className="data-table"><table><thead><tr><th>Tier</th><th>Evidence</th><th>Source</th><th>Captured</th></tr></thead><tbody>{report.evidence.map((item) => <tr key={item.evidence_id} onClick={() => setSelected(item)} className="clickable"><td><span className="tier">{item.tier}</span></td><td><strong>{item.summary}</strong><small>{item.kind.replaceAll("_", " ")}</small></td><td>{item.source}</td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody></table></div></section>}

      {tab === "Impact" && <section className="workspace-panel tab-panel"><header><div><span className="section-label">BLAST RADIUS</span><h2>{report.blast_radius.length} downstream assets</h2></div></header><div className="asset-list">{report.blast_radius.length ? report.blast_radius.map((item, index) => <div key={item}><span>{index + 1}</span><strong>{item}</strong></div>) : <p className="empty-copy">No downstream assets were identified.</p>}</div></section>}

      {tab === "Actions" && <section className="workspace-panel tab-panel"><header><div><span className="section-label">GOVERNED REMEDIATION</span><h2>Proposed action</h2></div></header>{report.remediation ? <div className="action-plan"><dl>{Object.entries(report.remediation).filter(([key]) => ["action", "risk", "reason", "rollback", "status"].includes(key)).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{String(value)}</dd></div>)}</dl><div className="action-buttons">{report.state === "AWAITING_APPROVAL" && !report.approved && <button onClick={() => void act("approve")} disabled={actionBusy}>Approve proposal</button>}{report.state === "AWAITING_APPROVAL" && report.approved && <button onClick={() => void act("execute")} disabled={actionBusy}>Execute approved recovery</button>}<span>Mutations require explicit human approval.</span></div>{actionError && <p className="inline-error">{actionError}</p>}</div> : <p className="empty-copy">No remediation proposal has been generated.</p>}</section>}
      <EvidenceDrawer evidence={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
