"use client";

import { useEffect, useState } from "react";
import ScopedLink from "../components/ScopedLink";
import DraftShell from "../DraftShell";
import styles from "../workflow.module.css";
import { scopedApiUrl } from "../../lib/client-workspace";
import { PageHeader } from "../components/ui";

type Item = Record<string, unknown>;
type Incident = Item & {
  incident_id: string; status: string; title: string; severity: string; first_divergence: string;
  root_cause: string; root_cause_confidence: number; failed_check_count: number;
  evidence: Item[]; hypotheses: Item[]; agents: Item[]; remediation: Item;
};

function statusLabel(value: unknown, fallback = "Not available"): string {
  const state = value == null || value === "" ? "" : String(value).toUpperCase();
  const labels: Record<string, string> = {
    AWAITING_APPROVAL: "Awaiting approval", APPROVED: "Approved", RESOLVED: "Resolved",
    REMEDIATED_PENDING_VERIFICATION: "Pending verification", MANUAL_ACTION_REQUIRED: "Manual action required",
    REMEDIATION_FAILED: "Remediation failed", FAILED: "Failed", OPEN: "Open",
  };
  return labels[state] ?? (state ? String(value).replaceAll("_", " ") : fallback);
}
function affectedAssets(incident: Incident): string {
  const values = Array.isArray(incident.affected_assets) ? incident.affected_assets : incident.affected_asset ? [incident.affected_asset] : [];
  return values.map(String).join(", ") || "Asset scope not recorded";
}
function nextAction(incident: Incident): string {
  const remediation = incident.remediation && typeof incident.remediation === "object" ? incident.remediation as Item : {};
  return String(remediation.action ?? incident.next_action ?? "Review the supporting evidence and choose a governed action.");
}
function confirmedCause(incident: Incident): string {
  return typeof incident.confirmed_cause === "string" && incident.confirmed_cause.trim()
    ? incident.confirmed_cause
    : "Not confirmed by the persisted evidence.";
}
function possibleCause(incident: Incident): string {
  const causes = Array.isArray(incident.possible_causes) ? incident.possible_causes : [];
  const supported = causes.find((item) => item && typeof item === "object" && String((item as Item).status).toUpperCase() === "SUPPORTED");
  return supported && typeof (supported as Item).statement === "string"
    ? String((supported as Item).statement)
    : String(incident.root_cause || "No supported cause identified.");
}

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [alerts, setAlerts] = useState<Item[]>([]);
  const [openCount, setOpenCount] = useState(0);
  const [openAlertCount, setOpenAlertCount] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = () => fetch(scopedApiUrl("/api/quality-incidents"), { cache: "no-store" }).then(async (response) => {
    const value = await response.json() as { incidents?: Incident[]; alerts?: Item[]; error?: string };
    if (!response.ok) throw new Error(value.error || "Unable to load incidents");
    setIncidents(value.incidents ?? []); setAlerts(value.alerts ?? []);
    setOpenCount(Number((value as Record<string, unknown>).openCount ?? 0));
    setOpenAlertCount(Number((value as Record<string, unknown>).openAlertCount ?? 0));
    setSelected((current) => current ?? value.incidents?.[0]?.incident_id ?? null);
  }).catch((error: Error) => setNotice(error.message));
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("incident_id");
    if (!requested || !incidents.some((item) => item.incident_id === requested)) return;
    setSelected(requested);
    window.requestAnimationFrame(() => document.querySelector('button[aria-pressed="true"]')?.scrollIntoView({ block: "center", behavior: "smooth" }));
  }, [incidents]);
  const act = async (action: string, incidentId: string) => {
    setBusy(action); setNotice(null);
    try {
      const response = await fetch(scopedApiUrl("/api/quality-incidents"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, incidentId, approvedBy: "ui-operator" }) });
      const value = await response.json() as { error?: string };
      if (!response.ok) throw new Error(value.error || `${action} failed`);
      setNotice(`${action} completed and persisted.`); await load();
    } catch (error) { setNotice(error instanceof Error ? error.message : `${action} failed`); }
    finally { setBusy(null); }
  };
  const incident = incidents.find((item) => item.incident_id === selected) ?? null;

  return <DraftShell active="incidents"><PageHeader eyebrow="AUTOMATED OPERATIONS / EVIDENCE-BACKED" title="Incidents" description="A DQ incident is created from a failed persisted execution with attributable evidence. Investigation is a separate RCA workspace." status={<span className={styles.draftBadge}>{openCount} OPEN · {openAlertCount} ALERTS</span>} actions={<button className={styles.secondary} onClick={() => void load()}>Refresh</button>} />
    {notice && <div className={notice.includes("failed") || notice.includes("required") ? styles.dangerStrip : styles.successStrip} role="status" aria-live="polite">{notice}</div>}
    <div className={styles.planLayout}><section className={styles.panel}><header className={styles.panelHead}><div><h2>Detected incidents</h2><p>Each item links to the failed run and its supporting evidence.</p></div><span>{incidents.length} PERSISTED</span></header>{!incidents.length ? <div className={styles.infoStrip}><span>✓</span><div><strong>No incident available</strong><p>A failed persisted execution is required before an incident appears.</p><ScopedLink className={styles.tableLink} href="/monitoring">Open Monitoring →</ScopedLink></div></div> : <div className={styles.analysisTable}><table className={styles.testTable}><thead><tr><th>Incident</th><th>Boundary</th><th>Failures</th><th>Status</th></tr></thead><tbody>{incidents.map((item) => <tr key={item.incident_id}><td className={styles.testName}><button className={styles.tableRowButton} aria-pressed={selected === item.incident_id} onClick={() => setSelected(item.incident_id)}><strong>{item.title}</strong><small>{item.incident_id}</small></button></td><td>{item.first_divergence}</td><td>{item.failed_check_count}</td><td><span className={`${styles.evidence} ${item.status === "RESOLVED" ? styles.parsed : styles.conflict}`}>{statusLabel(item.status)}</span></td></tr>)}</tbody></table></div>}</section>
    <aside className={styles.sideStack}><section className={styles.panel}><h3>Incident context</h3><p className={styles.rightNote}>Incidents are created from failed persisted executions with supporting evidence. Open Investigations for root-cause analysis.</p><ScopedLink className={styles.tableLink} href="/investigations">Open investigations →</ScopedLink></section></aside></div>
    {incident && <div className={styles.sectionStack}><section className={styles.panel}><header className={styles.panelHead}><div><h2>{incident.title}</h2><p>{possibleCause(incident)}</p></div><span>{String(incident.cause_status ?? "POSSIBLE").replaceAll("_", " ")}</span></header><div className={styles.incidentSummary}><div><small>What failed</small><strong>{incident.title}</strong></div><div><small>Impact</small><strong>{affectedAssets(incident)}</strong></div><div><small>Possible cause</small><strong>{possibleCause(incident)}</strong></div><div><small>Next action</small><strong>{nextAction(incident)}</strong></div></div><div className={styles.summaryList}><div className={styles.summaryRow}><span>Confirmed cause</span><strong>{confirmedCause(incident)}</strong></div><div className={styles.summaryRow}><span>State</span><strong>{statusLabel(incident.status)}</strong></div><div className={styles.summaryRow}><span>Execution run</span><strong>{String(incident.run_id)}</strong></div><div className={styles.summaryRow}><span>Data-quality certification</span><strong>{statusLabel(incident.certification ?? "FAILED")}</strong></div></div></section>
      <div className={styles.designerGrid}><section className={styles.panel}><header className={styles.panelHead}><div><h2>Direct evidence</h2><p>Raw failing adapter results are retained with evidence tiers and source attribution.</p></div><span>{incident.evidence.length} ITEMS</span></header><div className={styles.analysisTable}><table className={styles.testTable}><thead><tr><th>Tier</th><th>Summary</th><th>Source</th></tr></thead><tbody>{incident.evidence.map((item) => <tr key={String(item.evidence_id)}><td>{String(item.tier)}</td><td className={styles.testName}><strong>{String(item.summary)}</strong></td><td>{String(item.source)}</td></tr>)}</tbody></table></div></section><aside className={styles.sideStack}><section className={styles.panel}><h3>Specialist agents</h3><div className={styles.workflowSteps}>{incident.agents.map((item, index) => <div className={styles.workflowStep} key={`${String(item.name)}-${index}`}><span>{index + 1}</span><div><strong>{String(item.name).replaceAll("_", " ")}</strong><small>{String(item.claim)}</small></div><b>{String(item.status)}</b></div>)}</div></section></aside></div>
      <div className={styles.designerGrid}><section className={styles.panel}><header className={styles.panelHead}><div><h2>Competing hypotheses</h2><p>Possible causes stay separate from confirmed evidence.</p></div></header><div className={styles.summaryList}>{incident.hypotheses.map((item) => <div className={styles.summaryRow} key={String(item.hypothesis_id)}><span>{String(item.statement)}</span><strong>{statusLabel(item.status)} · {Math.round(Number(item.confidence) * 100)}%</strong></div>)}</div></section><aside className={styles.sideStack}><section className={styles.panel}><h3>Governed remediation</h3><p className={styles.rightNote}>{String(incident.remediation.action)} · {String(incident.remediation.risk)}</p><div className={styles.summaryList}><div className={styles.summaryRow}><span>Executor</span><strong>{String(incident.remediation.executor ?? "Manual")}</strong></div><div className={styles.summaryRow}><span>Approved by</span><strong>{String(incident.remediation.approved_by ?? "—")}</strong></div></div><div className={styles.toolbar}>{incident.status === "AWAITING_APPROVAL" && <button className={styles.primary} disabled={busy !== null} onClick={() => void act("approve", incident.incident_id)}>Approve remediation</button>}{incident.status === "APPROVED" && <button className={styles.primary} disabled={busy !== null} onClick={() => void act("execute", incident.incident_id)}>Execute approved action</button>}{["REMEDIATED_PENDING_VERIFICATION", "MANUAL_ACTION_REQUIRED", "REMEDIATION_FAILED"].includes(incident.status) && <button className={styles.primary} disabled={busy !== null} onClick={() => void act("verify", incident.incident_id)}>Verify with approved plan</button>}</div></section></aside></div>
    </div>}
  </DraftShell>;
}
