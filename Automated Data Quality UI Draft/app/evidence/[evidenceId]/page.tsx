"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import DraftShell from "../../DraftShell";
import styles from "../../workflow.module.css";

type EvidenceRecord = {
  evidence_id?: string;
  project_id?: string;
  environment?: string;
  asset_id?: string | null;
  local_run_id?: string | null;
  step_sequence?: number | null;
  source?: string;
  observed_at?: string;
  verification_state?: string;
  external_run_id?: string | null;
  external_query_id?: string | null;
  schema_version?: number;
  scope_state?: string;
  plan_id?: string | null;
  provider?: string | null;
  evidence_type?: string;
  origin?: string;
  payload?: unknown;
};

function recordValue(value: unknown): EvidenceRecord {
  return value && typeof value === "object" ? value as EvidenceRecord : {};
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value);
}

function dateTime(value?: string): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function label(value: unknown): string {
  return display(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function EvidencePage() {
  const params = useParams<{ evidenceId: string }>();
  const searchParams = useSearchParams();
  const evidenceId = Array.isArray(params.evidenceId) ? params.evidenceId[0] : params.evidenceId;
  const [record, setRecord] = useState<EvidenceRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!evidenceId) return;
    const query = searchParams.toString();
    fetch(`/api/evidence/${encodeURIComponent(evidenceId)}${query ? `?${query}` : ""}`, { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(body && typeof body === "object" && "error" in body ? String(body.error) : `Evidence request failed (${response.status})`);
        return body;
      })
      .then((body) => setRecord(recordValue(body)))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Evidence could not be loaded"));
  }, [evidenceId, searchParams]);

  const projectId = searchParams.get("project_id") ?? record?.project_id ?? "";
  const environment = searchParams.get("environment") ?? record?.environment ?? "";

  return <DraftShell active="agent">
    <header className={styles.topbar}>
      <div>
        <span className={styles.eyebrow}>EVIDENCE / DETAIL</span>
        <h1>Evidence record</h1>
        <p>Readable details for one exact observation. The raw payload is available below for technical inspection.</p>
      </div>
      <span className={styles.draftBadge}>{record?.verification_state ?? (error ? "UNAVAILABLE" : "LOADING")}</span>
    </header>
    <div className={styles.askAiLayout}>
      <section className={styles.panel}>
        {error ? <div className={styles.dangerStrip} role="alert">{error}</div> : !record ? <p className={styles.muted}>Loading evidence…</p> : <>
          <div className={styles.answerCard}>
            <div className={styles.answerHeader}><span className={styles.answerEyebrow}>OBSERVATION</span><span className={styles.answerStatus}>{display(record.verification_state)}</span></div>
            <h2>{display(record.source).replaceAll("_", " ")}</h2>
            <p>Recorded {dateTime(record.observed_at)} for the selected project and environment.</p>
            <div className={styles.answerFacts}>
              <div className={styles.answerFact}><small>Evidence ID</small><strong>{display(record.evidence_id)}</strong></div>
              <div className={styles.answerFact}><small>Project</small><strong>{display(projectId)}</strong></div>
              <div className={styles.answerFact}><small>Environment</small><strong>{display(environment)}</strong></div>
              <div className={styles.answerFact}><small>Scope</small><strong>{display(record.scope_state)}</strong></div>
              <div className={styles.answerFact}><small>Evidence type</small><strong>{label(record.evidence_type)}</strong></div>
              <div className={styles.answerFact}><small>Provider</small><strong>{display(record.provider)}</strong></div>
            </div>
          </div>
          <section><h3>Execution context</h3><div className={styles.summaryList}>
            <div className={styles.summaryRow}><span>Asset</span><strong>{display(record.asset_id)}</strong></div>
            <div className={styles.summaryRow}><span>Local run</span><strong>{display(record.local_run_id)}</strong></div>
            <div className={styles.summaryRow}><span>External run</span><strong>{display(record.external_run_id)}</strong></div>
            <div className={styles.summaryRow}><span>External query</span><strong>{display(record.external_query_id)}</strong></div>
            <div className={styles.summaryRow}><span>Step</span><strong>{display(record.step_sequence)}</strong></div>
            <div className={styles.summaryRow}><span>Plan</span><strong>{display(record.plan_id)}</strong></div>
            <div className={styles.summaryRow}><span>Origin</span><strong>{display(record.origin)}</strong></div>
          </div></section>
          <details><summary>Technical payload</summary><pre className={styles.codeViewer}><code>{JSON.stringify(record.payload ?? {}, null, 2)}</code></pre></details>
          <div className={styles.toolbar}><a className={styles.secondary} href={`/agent?project_id=${encodeURIComponent(projectId)}&environment=${encodeURIComponent(environment)}`}>Back to Ask AI</a></div>
        </>}
      </section>
    </div>
  </DraftShell>;
}
