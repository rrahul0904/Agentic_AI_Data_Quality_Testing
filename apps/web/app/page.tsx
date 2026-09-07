"use client";

import { useEffect, useState } from "react";

type Project = { project_id: string; name: string; created_at: string };
type Run = { run_id: string; project_id: string; environment_id: string; intent: string; state: string; created_at: string };
type Approval = { approval_id: string; run_id: string; scope: string; approved: boolean; environment?: string | null };

const API = process.env.NEXT_PUBLIC_ADE_API_URL ?? "http://127.0.0.1:8001";
const nav = ["Portfolio", "Assessment", "Migration waves", "Run detail", "Reconciliation", "Approvals", "Connections"];

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [active, setActive] = useState("Portfolio");
  const [status, setStatus] = useState("Connecting to control plane…");

  useEffect(() => {
    async function load() {
      try {
        const [projectsResponse, runsResponse, approvalsResponse] = await Promise.all([
          fetch(`${API}/projects`), fetch(`${API}/runs`), fetch(`${API}/approvals`),
        ]);
        if (![projectsResponse, runsResponse, approvalsResponse].every((response) => response.ok)) throw new Error("Control plane unavailable");
        setProjects(await projectsResponse.json());
        setRuns(await runsResponse.json());
        setApprovals(await approvalsResponse.json());
        setStatus("Connected · local control plane");
      } catch {
        setStatus("Waiting for API at " + API);
      }
    }
    void load();
  }, []);

  const latestRun = runs.at(-1);
  const latestApproval = latestRun ? approvals.find((approval) => approval.run_id === latestRun.run_id) : undefined;

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">U</span><span>UMA</span></div>
        <p className="workspace">UNIFIED MIGRATION ACCELERATOR</p>
        <nav>{nav.map((item) => <button className={active === item ? "nav-item active" : "nav-item"} key={item} onClick={() => setActive(item)}>{item}</button>)}</nav>
        <div className="safety-card"><span className="dot" /> Governed migration<br /><small>Mutations require approval</small></div>
      </aside>

      <section className="content">
        <header className="topbar"><div><p className="eyebrow">{active}</p><h1>Move data estates, with proof.</h1></div><div className="connection"><span className="dot" /> {status}</div></header>

        <section className="metrics">
          <article><p>Migration portfolios</p><strong>{projects.length}</strong><span>persisted locally</span></article>
          <article><p>Active migration runs</p><strong>{runs.filter((run) => !["succeeded", "failed", "cancelled"].includes(run.state)).length}</strong><span>governed workflows</span></article>
          <article><p>Approval coverage</p><strong>{approvals.filter((approval) => approval.approved).length}</strong><span>scoped decisions</span></article>
          <article><p>Reconciliation</p><strong>Fail closed</strong><span>deterministic gates</span></article>
        </section>

        <section className="grid">
          <article className="panel run-panel">
            <div className="panel-heading"><div><p className="eyebrow">LATEST MIGRATION RUN</p><h2>{latestRun ? latestRun.intent : "Start a migration assessment"}</h2></div><span className={latestRun ? "badge pending" : "badge muted"}>{latestRun ? label(latestRun.state) : "No runs"}</span></div>
            <div className="run-meta"><span>{latestRun ? `Run ${latestRun.run_id.slice(0, 12)}` : "Create a migration run through the API"}</span><span>{latestRun?.environment_id ?? "—"}</span></div>
            <div className="timeline">
              {["Discover", "Assess", "Plan wave", "Verify", "Approve", "Execute"].map((step, index) => <div className={index < 2 && latestRun ? "step complete" : "step"} key={step}><i>{index + 1}</i><span>{step}</span></div>)}
            </div>
            <div className="run-footer"><span>{latestApproval ? `Approval recorded: ${latestApproval.scope}` : "No approval recorded"}</span><button>View run detail →</button></div>
          </article>

          <article className="panel gates"><div className="panel-heading"><div><p className="eyebrow">MIGRATION ASSURANCE</p><h2>Evidence gates</h2></div><span className="badge success">Policy protected</span></div>
            {["Source schema captured", "SQL safety classification", "Target compatibility", "Partition reconciliation"].map((gate, index) => <div className="gate" key={gate}><span className={index < 2 ? "check pass" : "check"}>{index < 2 ? "✓" : "·"}</span><span>{gate}</span><small>{index < 2 ? "ready" : "awaiting wave"}</small></div>)}
          </article>
        </section>

        <section className="panel projects"><div className="panel-heading"><div><p className="eyebrow">MIGRATION PORTFOLIO</p><h2>Source estates and targets</h2></div><button className="primary">+ New migration</button></div>
          {projects.length ? <div className="project-list">{projects.map((project) => <div className="project-row" key={project.project_id}><span className="project-icon">▦</span><div><strong>{project.name}</strong><small>{project.project_id}</small></div><span className="tag">Assessment</span><button>Open →</button></div>)}</div> : <div className="empty"><strong>No migration portfolios yet</strong><span>Create a project through the API to begin discovery.</span></div>}
        </section>
      </section>
    </main>
  );
}
