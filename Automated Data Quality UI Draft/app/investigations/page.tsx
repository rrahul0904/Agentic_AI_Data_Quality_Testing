"use client";

import ScopedLink from "../components/ScopedLink";
import { useEffect, useState } from "react";
import DraftShell from "../DraftShell";
import styles from "../workflow.module.css";
import { scopedApiUrl } from "../../lib/client-workspace";
import { PageHeader, StatusBadge } from "../components/ui";

type Item = Record<string, unknown>;

function text(value: unknown, fallback = "—"): string {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function statusLabel(value: unknown, fallback = "Not available"): string {
  const state = value == null || value === "" ? "" : String(value).toUpperCase();
  const labels: Record<string, string> = { NOT_RUN: "Not run", OPEN: "Open", FAILED: "Failed", RESOLVED: "Resolved", PENDING: "Pending" };
  return labels[state] ?? (state ? String(value).replaceAll("_", " ") : fallback);
}

export default function InvestigationsPage() {
  const [investigations, setInvestigations] = useState<Item[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = () => fetch(scopedApiUrl("/api/investigations"), { cache: "no-store" }).then(async (response) => {
    const value = await response.json() as { investigations?: { incidents?: Item[] }; error?: string };
    if (!response.ok) throw new Error(value.error || "Unable to load investigations");
    setInvestigations(value.investigations?.incidents ?? []);
  }).catch((reason: Error) => setError(reason.message));

  useEffect(() => { void load(); }, []);

  return <DraftShell active="investigations">
    <PageHeader eyebrow="AUTOMATED DATA QUALITY / RCA" title="Investigations" description="Investigations explain an observed execution or quality incident. They do not exist before execution evidence." status={<StatusBadge value={investigations.length ? "COMPLETED" : "NOT_RUN"} label={investigations.length ? `${investigations.length} CASES` : "NOT RUN"} />} actions={<button className={styles.secondary} onClick={() => void load()}>Refresh</button>} />
    {error && <div className={styles.dangerStrip} role="alert">{error}</div>}
    <div className={styles.planLayout}>
      <main className={styles.sectionStack}>
        <section className={styles.panel}>
          <header className={styles.panelHead}><div><h2>Current investigations</h2><p>Only persisted investigation records appear here. No demo RCA is presented as a real event.</p></div><span>{investigations.length} PERSISTED</span></header>
          {!investigations.length ? <div className={styles.infoStrip}><span>i</span><div><strong>No investigation available</strong><p>Run evidence is required before an investigation can start.</p><ScopedLink className={styles.tableLink} href="/monitoring">Open Monitoring →</ScopedLink></div></div> : <div className={styles.analysisTable}><table className={styles.testTable}><thead><tr><th>Case</th><th>Asset</th><th>Status</th><th>Created</th></tr></thead><tbody>{investigations.map((item, index) => <tr key={text(item.incident_id, `case-${index}`)}><td className={styles.testName}><strong>{text(item.title, text(item.incident_id, "Investigation"))}</strong><small>{text(item.incident_id)}</small></td><td>{text(item.affected_asset)}</td><td><span className={styles.evidence}>{statusLabel(item.status, "Open")}</span></td><td>{text(item.created_at)}</td></tr>)}</tbody></table></div>}
        </section>
        <section className={styles.panel}>
          <header className={styles.panelHead}><div><h2>Start an investigation</h2><p>Investigation actions appear here only after an eligible incident with persisted execution evidence is selected.</p></div><span>WAITING FOR INCIDENT</span></header>
          <div className={styles.infoStrip}><span>i</span><div><strong>No investigation action available</strong><p>There are no eligible incidents in the current project. Run and verify a scoped job before starting an investigation.</p><ScopedLink className={styles.tableLink} href="/incidents">Review incidents →</ScopedLink></div></div>
        </section>
      </main>
      <aside className={styles.sideStack}>
        <section className={styles.panel}><h3>Evidence boundary</h3><div className={styles.summaryList}><div className={styles.summaryRow}><span>Before a run</span><strong>Not available</strong></div><div className={styles.summaryRow}><span>After a failed run</span><strong>Investigate</strong></div><div className={styles.summaryRow}><span>RCA conclusion</span><strong>Evidence required</strong></div></div><p className={styles.rightNote}>Only persisted execution evidence can start RCA.</p></section>
        <section className={styles.panel}><h3>Related operational surfaces</h3><div className={styles.linkStack}><ScopedLink className={styles.tableLink} href="/incidents">Open incidents →</ScopedLink><ScopedLink className={styles.tableLink} href="/test-plan?view=execution&mode=manage">Open runs &amp; evidence →</ScopedLink><ScopedLink className={styles.tableLink} href="/reconciliation">Open reconciliation →</ScopedLink></div></section>
      </aside>
    </div>
  </DraftShell>;
}
