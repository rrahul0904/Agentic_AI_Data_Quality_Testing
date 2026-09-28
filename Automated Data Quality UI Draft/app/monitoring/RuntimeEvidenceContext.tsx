import type { ProjectAnalysisReport } from "../../lib/project-analysis";
import { lineageRuntimeRefresh, type RuntimeExecutionReference } from "../../lib/runtime-status-consistency";
import { monitoringStatusLabel } from "../../lib/ui-contracts";
import ScopedLink from "../components/ScopedLink";
import shared from "../workflow.module.css";
import local from "./monitoring.module.css";

function date(value?: string | null) { if (!value) return "Not recorded"; const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? "Not recorded" : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); }
function technology(kind: string) { return kind === "airflow_trigger" ? "Airflow" : kind === "dbt_execute" ? "dbt" : kind.replaceAll("_", " ") || "Pipeline"; }

export default function RuntimeEvidenceContext({ report, executions, loading, checkedAt, reportError, executionsError, onSelectRun }: { report: ProjectAnalysisReport | null; executions: RuntimeExecutionReference[]; loading: boolean; checkedAt: string | null; reportError?: string; executionsError?: string; onSelectRun: (runId: string) => void }) {
  const snapshot = lineageRuntimeRefresh(report);
  return <section className={`${shared.panel} ${local.runtimeEvidence}`} aria-labelledby="runtime-evidence-context-title">
    <header className={shared.panelHead}><div><span className={shared.eyebrow}>CROSS-PAGE EXECUTION EVIDENCE</span><h2 id="runtime-evidence-context-title">Lineage runtime snapshot</h2><p>Saved lineage refreshes and persisted job runs are separate records. Exact asset matches are navigation aids only.</p></div><ScopedLink className={`${shared.secondary} ${shared.linkButton}`} href="/project-design?view=map">Open lineage</ScopedLink></header>
    {loading && <p role="status">Loading saved lineage and run evidence…</p>}
    {reportError && <p role="status">Lineage snapshot unavailable: {reportError}</p>}
    {report && <div className={local.runtimeSnapshot}><div><span>Snapshot status</span><strong>{monitoringStatusLabel(snapshot.status)}</strong></div><div><span>Last runtime refresh</span><strong>{date(snapshot.refreshedAt)}</strong></div><div><span>Accepted analysis</span><strong>{date(snapshot.analysisCreatedAt)}</strong></div><div><span>Observed</span><strong>{snapshot.observedNodes} nodes · {snapshot.observedEdges} edges</strong></div><p>{snapshot.refreshedAt ? snapshot.note : "No runtime refresh is recorded. Persisted executions below have not been incorporated into the lineage snapshot."}</p>{checkedAt && <small>Checked {date(checkedAt)} · read-only; no runtime refresh was triggered.</small>}</div>}
    <h3>Persisted executions matching lineage assets · {executions.length}</h3>
    {executionsError && <p role="status">Run records unavailable: {executionsError}</p>}
    {!loading && !executionsError && !executions.length && <p>No exact asset-name matches found in recent persisted runs.</p>}
    {executions.map((item) => <article className={local.runtimeMatch} key={`${item.runId}:${item.assetName}`}><div><strong>{item.assetName}</strong><small>{technology(item.kind)} · execution {monitoringStatusLabel(item.executionStatus)} · verification {monitoringStatusLabel(item.verificationStatus)} · data quality {monitoringStatusLabel(item.dataQualityStatus)}</small><small>{item.scopeMatch === "MATCHED" ? "Project, environment and source-table scope match." : "Asset name matches, but source-table scope is not recorded on both records."}</small><small>Last observed {date(item.lastObserved)}{item.externalIdentifier ? <> · external ID <code>{item.externalIdentifier}</code></> : null}</small></div><button className={shared.secondary} onClick={() => onSelectRun(item.runId)}>Open exact run</button></article>)}
    <p className={local.runtimeEvidenceNote}>A persisted execution does not itself mark lineage edges observed. An Airflow run does not prove a Snowflake load or dbt run.</p>
  </section>;
}
