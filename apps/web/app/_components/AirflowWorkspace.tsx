"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { AirflowEvidence, Lifecycle } from "./types";
import { useLiveData } from "./use-live-data";
import LifecycleView from "./Lifecycle";

type Overview = { status: string; mode: string; reason?: string; dags: Record<string, unknown>[]; health: Record<string, unknown>; version: Record<string, unknown>; last_updated: string };

export function AirflowOverview() {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const { data, error, loading, updatedAt, refresh } = useLiveData<Overview>("/api/v1/airflow/runtime/overview?limit=250", 10000);
  const filtered = useMemo(() => (data?.dags ?? []).filter((item) => String(item.dag_id || item.dagId || "").toLowerCase().includes(query.toLowerCase())), [data, query]);
  const rows = filtered.slice(page * 20, page * 20 + 20);
  return <div>
    <section className="workspace-heading"><div><span>AIRFLOW</span><h1>Runtime operations</h1><p>DAG, run, and task lifecycle evidence with explicit availability.</p></div><div className="live-meta"><i className={data?.status === "AVAILABLE" ? "" : "offline"} />{data?.status === "AVAILABLE" ? "Live API" : "Repository fallback"} · {updatedAt?.toLocaleTimeString() || "connecting"}</div></section>
    {loading && !data ? <div className="full-state"><span className="spinner" />Loading Airflow state…</div> : error && !data ? <div className="full-state error"><strong>Airflow unavailable</strong><span>{error}</span></div> : data && <>
      {data.status !== "AVAILABLE" && <div className="availability-banner"><strong>Live runtime unavailable</strong><span>{data.reason}</span><code>{data.mode}</code></div>}
      <section className="runtime-strip"><div><span>DAGs visible</span><strong>{data.dags.length}</strong></div><div><span>Scheduler</span><strong>{String((data.health?.scheduler as Record<string, unknown> | undefined)?.status ?? data.health?.status ?? "NOT AVAILABLE")}</strong></div><div><span>Executor</span><strong>{String(data.health?.executor ?? "NOT AVAILABLE")}</strong></div><div><span>Version</span><strong>{String(data.version?.version ?? data.version?.status ?? "NOT AVAILABLE")}</strong></div></section>
      <section className="workspace-panel"><header><div><span className="section-label">DAGS</span><h2>Orchestration inventory</h2></div><div className="table-actions"><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} placeholder="Search DAGs" aria-label="Search DAGs" /><button onClick={() => void refresh()}>Refresh</button></div></header>
        {!filtered.length ? <p className="empty-copy">No DAGs match this filter.</p> : <div className="data-table"><table><thead><tr><th>DAG</th><th>Schedule</th><th>State</th><th>Source</th></tr></thead><tbody>{rows.map((item, index) => { const id = String(item.dag_id || item.dagId || item.name || `dag-${index}`); return <tr key={id}><td><Link className="table-link mono" href={`/airflow/dags/${encodeURIComponent(id)}`}>{id}</Link></td><td>{String(item.schedule || item.schedule_interval || "—")}</td><td>{String(item.is_paused === true ? "PAUSED" : item.state || "DISCOVERED")}</td><td>{String(item.source || data.mode)}</td></tr>; })}</tbody></table></div>}
        <footer className="pagination"><span>{filtered.length} DAGs</span><div><button disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Previous</button><span>Page {page + 1}</span><button disabled={(page + 1) * 20 >= filtered.length} onClick={() => setPage((value) => value + 1)}>Next</button></div></footer>
      </section>
    </>}
  </div>;
}

type DagDetail = { dag_id?: string; schedule?: string; tasks?: string[]; status?: string; reason?: string };
type Runs = { status?: string; dag_runs?: Record<string, unknown>[]; dagRuns?: Record<string, unknown>[]; reason?: string };

export function AirflowDag({ dagId }: { dagId: string }) {
  const { data: detail, error: detailError } = useLiveData<DagDetail>(`/api/v1/airflow/dags/${encodeURIComponent(dagId)}`);
  const { data: runs, error: runError, refresh } = useLiveData<Runs>(`/api/v1/airflow/dags/${encodeURIComponent(dagId)}/runs?limit=50`, 10000);
  const items = runs?.dag_runs || runs?.dagRuns || [];
  return <div><section className="workspace-heading"><div><span>AIRFLOW / DAG</span><h1 className="mono">{dagId}</h1><p>{detail?.schedule ? `Schedule ${detail.schedule}` : "Static definition and live run history"}</p></div><button className="outline-button" onClick={() => void refresh()}>Refresh runs</button></section>
    {(detailError || runError) && <div className="availability-banner"><strong>Partial Airflow availability</strong><span>{detailError || runError}</span></div>}
    <section className="workspace-panel"><header><div><span className="section-label">RECENT RUNS</span><h2>DAG run history</h2></div></header>{!items.length ? <div className="state-panel"><strong>No live run history available</strong><span>{runs?.reason || "Configure ADE_AIRFLOW_URL and runtime permissions to retrieve DAG runs."}</span></div> : <div className="data-table"><table><thead><tr><th>Run ID</th><th>State</th><th>Start</th><th>End</th></tr></thead><tbody>{items.map((item, index) => { const runId = String(item.dag_run_id || item.dagRunId || item.run_id || `run-${index}`); return <tr key={runId}><td><Link className="table-link mono" href={`/airflow/dags/${encodeURIComponent(dagId)}/runs/${encodeURIComponent(runId)}`}>{runId}</Link></td><td>{String(item.state || "UNKNOWN")}</td><td>{String(item.start_date || item.startDate || "—")}</td><td>{String(item.end_date || item.endDate || "—")}</td></tr>; })}</tbody></table></div>}</section>
  </div>;
}

type RunDetail = { status: string; mode: string; reason?: string; dag_id: string; run_id: string; tasks: Lifecycle[]; executor?: string; parallelism?: number };

export function AirflowRun({ dagId, runId, incidentId }: { dagId: string; runId: string; incidentId?: string }) {
  const endpoint = incidentId ? `/api/v1/investigations/${encodeURIComponent(incidentId)}/airflow` : `/api/v1/airflow/dags/${encodeURIComponent(dagId)}/runs/${encodeURIComponent(runId)}`;
  const { data, error, loading, updatedAt, refresh } = useLiveData<RunDetail>(endpoint, 4000);
  const tasks = data?.tasks ?? [];
  return <div><section className="workspace-heading"><div><span>AIRFLOW / DAG RUN</span><h1 className="mono">{dagId}</h1><p className="mono">{runId}</p></div><div className="incident-actions"><span>Updated {updatedAt?.toLocaleTimeString() || "—"}</span><button onClick={() => void refresh()}>Refresh</button>{incidentId && <Link className="primary-link" href={`/investigations/${incidentId}`}>Back to RCA</Link>}</div></section>
    {loading && !data ? <div className="full-state"><span className="spinner" />Reconstructing task lifecycles…</div> : error && !data ? <div className="full-state error"><strong>Run unavailable</strong><span>{error}</span></div> : data && <>
      {data.status !== "AVAILABLE" && <div className="availability-banner warning"><strong>Live Airflow runtime unavailable</strong><span>{data.reason}</span><code>{data.mode}</code></div>}
      <section className="runtime-strip"><div><span>Tasks</span><strong>{tasks.length}</strong></div><div><span>Queued</span><strong>{tasks.filter((item) => item.metadata_state === "QUEUED").length}</strong></div><div><span>Running observed</span><strong>{tasks.filter((item) => item.runtime_start_proven).length}</strong></div><div><span>Executor</span><strong>{data.executor || tasks[0]?.executor || "NOT AVAILABLE"}</strong></div><div><span>Parallelism</span><strong>{data.parallelism ?? tasks[0]?.parallelism ?? "—"}</strong></div></section>
      <section className="workspace-panel"><header><div><span className="section-label">TASK INSTANCES</span><h2>Execution boundary reconstruction</h2></div></header>{!tasks.length ? <p className="empty-copy">No task-instance evidence was returned.</p> : <div className="data-table"><table><thead><tr><th>Task</th><th>Metadata</th><th>Executor</th><th>Queue time</th><th>Runtime</th><th>Try</th></tr></thead><tbody>{tasks.map((task) => <tr key={task.task_id}><td><Link className="table-link mono" href={`/airflow/dags/${encodeURIComponent(dagId)}/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(task.task_id)}${incidentId ? `?incident=${encodeURIComponent(incidentId)}` : ""}`}>{task.task_id}</Link></td><td>{task.metadata_state || "UNKNOWN"}</td><td>{task.executor_state || "UNKNOWN"}</td><td>{task.queued_duration_seconds ? `${Math.round(task.queued_duration_seconds)}s` : "—"}</td><td>{task.runtime_start_proven ? "Observed" : "Not observed"}</td><td>{task.try_number ?? "—"}</td></tr>)}</tbody></table></div>}</section>
    </>}</div>;
}

export function AirflowTask({ dagId, runId, taskId, incidentId }: { dagId: string; runId: string; taskId: string; incidentId?: string }) {
  const endpoint = incidentId ? `/api/v1/investigations/${encodeURIComponent(incidentId)}/airflow` : `/api/v1/airflow/dags/${encodeURIComponent(dagId)}/runs/${encodeURIComponent(runId)}`;
  const { data, error, loading, refresh } = useLiveData<AirflowEvidence>(endpoint, 5000);
  const task = data?.tasks.find((item) => item.task_id === taskId) || data?.tasks[0];
  return <div><section className="workspace-heading"><div><span>AIRFLOW / TASK INSTANCE</span><h1 className="mono">{taskId}</h1><p>{dagId} · <span className="mono">{runId}</span></p></div><button className="outline-button" onClick={() => void refresh()}>Refresh</button></section>
    {loading && !data ? <div className="full-state"><span className="spinner" />Loading task evidence…</div> : error && !data ? <div className="full-state error"><strong>Task unavailable</strong><span>{error}</span></div> : task ? <div className="task-layout"><section className="workspace-panel"><header><div><span className="section-label">EXECUTION LIFECYCLE</span><h2>What Airflow actually observed</h2></div></header><LifecycleView lifecycle={task} evidence={[]} /><div className="boundary-callout"><strong>{task.runtime_start_proven ? "Execution boundary crossed" : "Execution boundary not crossed"}</strong><p>{task.runtime_start_proven ? "A RUNNING transition was observed. Application-level RCA may proceed when operator start is also proven." : "RUNNING was not observed. ADE prohibits application, SQL, and watermark logic from being promoted as the primary root cause."}</p></div></section><aside className="workspace-panel"><span className="section-label">RUNTIME FACTS</span><dl className="fact-list"><div><dt>Metadata state</dt><dd>{task.metadata_state || "UNKNOWN"}</dd></div><div><dt>Executor state</dt><dd>{task.executor_state || "UNKNOWN"}</dd></div><div><dt>Task log</dt><dd>{task.task_log_exists === false ? "NOT AVAILABLE" : task.task_log_exists ? "AVAILABLE" : "UNKNOWN"}</dd></div><div><dt>Operator start</dt><dd>{task.operator_start_proven ? "PROVEN" : "NOT PROVEN"}</dd></div></dl>{incidentId && <Link className="primary-link block" href={`/investigations/${incidentId}`}>Open investigation evidence</Link>}</aside></div> : <div className="state-panel"><strong>Task evidence not found</strong><span>The runtime did not return this task instance.</span></div>}
  </div>;
}
