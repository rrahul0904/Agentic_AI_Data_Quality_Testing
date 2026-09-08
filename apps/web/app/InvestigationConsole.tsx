"use client";

import { useEffect, useState } from "react";
import { getJson, postJson } from "../lib/api";

type Scenario = {
  scenario_id: string;
  title: string;
  affected_asset: string;
};

type Agent = {
  role: string;
  identity: string;
};

type AgentResult = {
  role: string;
  status: string;
  claim: string;
  confidence: number;
  reasoning_summary: string;
  tools_used: string[];
};

type Evidence = {
  evidence_id: string;
  tier: string;
  kind: string;
  source: string;
  summary: string;
};

type Hypothesis = {
  hypothesis_id: string;
  name: string;
  statement: string;
  status: string;
  confidence: number;
  supporting_evidence_ids: string[];
};

type Transition = {
  from_state: string | null;
  to_state: string;
  reason: string;
  created_at: string;
};

type Investigation = {
  incident_id: string;
  scenario_id: string;
  mode: string;
  state: string;
  first_divergence: string | null;
  root_cause: string | null;
  root_cause_confidence: number;
  certification: string;
  approved: boolean;
  agent_results: AgentResult[];
  evidence: Evidence[];
  hypotheses: Hypothesis[];
  blast_radius: string[];
  transitions: Transition[];
  remediation: null | {
    action: string;
    reason: string;
    risk: string;
    rollback: string;
    requires_approval: boolean;
    status?: string;
    approved_by?: string | null;
  };
  verification_result: Record<string, unknown>;
};

function statusClass(value: string) {
  const normalized = value.toUpperCase();
  if (["PASS", "SUPPORTED", "RESOLVED", "CERTIFIED", "DIAGNOSED", "APPROVED"].includes(normalized)) {
    return "agentic-good";
  }
  if (["FAIL", "FAILED", "REJECTED", "BLOCKED", "ERROR"].includes(normalized)) {
    return "agentic-bad";
  }
  return "agentic-warn";
}

export default function InvestigationConsole() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState("watermark_defect");
  const [report, setReport] = useState<Investigation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([
      getJson<{ agents: Agent[] }>("/api/v1/agents/roster"),
      getJson<{ scenarios: Scenario[] }>("/api/v1/investigations/scenarios"),
    ]).then(([roster, catalog]) => {
      setAgents(roster.agents);
      setScenarios(catalog.scenarios);
    }).catch((cause) => setError(String(cause)));
  }, []);

  async function startInvestigation() {
    setBusy(true);
    setError(null);
    try {
      const path = "/api/v1/investigations/" + encodeURIComponent(scenario) + "/start";
      setReport(await postJson<Investigation>(path, {}));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function reload(incidentId: string) {
    setReport(await getJson<Investigation>("/api/v1/investigations/" + incidentId));
  }

  async function approve() {
    if (!report) return;
    setBusy(true);
    setError(null);
    try {
      await postJson("/api/v1/investigations/" + report.incident_id + "/approve", {
        approved_by: "operator-console",
      });
      await reload(report.incident_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function execute() {
    if (!report) return;
    setBusy(true);
    setError(null);
    try {
      setReport(
        await postJson<Investigation>(
          "/api/v1/investigations/" + report.incident_id + "/execute",
          {},
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="agentic-console">
      <section className="agentic-hero">
        <div>
          <p className="eyebrow">EVIDENCE-GROUNDED MULTI-AGENT CONTROL PLANE</p>
          <h2>Incident Investigation</h2>
          <p>
            Detect anomaly → delegate specialists → prove first divergence → establish RCA →
            calculate impact → propose remediation → approve → verify → certify.
          </p>
        </div>
        <div className="agentic-runner">
          <select value={scenario} onChange={(event) => setScenario(event.target.value)}>
            {scenarios.map((item) => (
              <option key={item.scenario_id} value={item.scenario_id}>
                {item.title}
              </option>
            ))}
          </select>
          <button onClick={() => void startInvestigation()} disabled={busy}>
            {busy ? "Working…" : "Start investigation"}
          </button>
        </div>
      </section>

      {error && (
        <div className="error-banner">
          <strong>Investigation error</strong>
          <span>{error}</span>
        </div>
      )}

      <section className="agentic-roster">
        {agents.map((agent) => (
          <article key={agent.role}>
            <span>{agent.role.replaceAll("_", " ")}</span>
            <strong>{agent.identity}</strong>
          </article>
        ))}
      </section>

      {!report ? (
        <section className="agentic-empty">
          <strong>No investigation running</strong>
          <p>Choose a failure scenario to watch the Supervisor delegate evidence-grounded work.</p>
        </section>
      ) : (
        <>
          <section className="agentic-kpis">
            <div>
              <span>Incident</span>
              <strong>{report.incident_id.slice(-10)}</strong>
            </div>
            <div>
              <span>State</span>
              <strong className={statusClass(report.state)}>{report.state}</strong>
            </div>
            <div>
              <span>First divergence</span>
              <strong>{report.first_divergence ?? "—"}</strong>
            </div>
            <div>
              <span>Root cause</span>
              <strong>{report.root_cause ?? "—"}</strong>
            </div>
            <div>
              <span>Confidence</span>
              <strong>{Math.round(report.root_cause_confidence * 100)}%</strong>
            </div>
            <div>
              <span>Certification</span>
              <strong className={statusClass(report.certification)}>{report.certification}</strong>
            </div>
          </section>

          <div className="agentic-grid">
            <section className="panel">
              <header className="panel-head">
                <div>
                  <p className="eyebrow">AGENT HANDOFFS</p>
                  <h2>Investigation timeline</h2>
                </div>
              </header>
              <div className="agentic-timeline">
                {report.agent_results.map((item, index) => (
                  <article key={item.role + "-" + index}>
                    <div className="agentic-step">{index + 1}</div>
                    <div>
                      <div className="agentic-line">
                        <strong>{item.role.replaceAll("_", " ")}</strong>
                        <span className={statusClass(item.status)}>{item.status}</span>
                      </div>
                      <p>{item.claim}</p>
                      <small>{item.reasoning_summary}</small>
                      {item.tools_used.length > 0 && <code>{item.tools_used.join(" · ")}</code>}
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel">
              <header className="panel-head">
                <div>
                  <p className="eyebrow">COMPETING CAUSES</p>
                  <h2>Hypotheses</h2>
                </div>
              </header>
              <div className="agentic-hypotheses">
                {report.hypotheses.map((item) => (
                  <article key={item.hypothesis_id}>
                    <div>
                      <strong>{item.name}</strong>
                      <span className={statusClass(item.status)}>{item.status}</span>
                    </div>
                    <p>{item.statement}</p>
                    <small>
                      {Math.round(item.confidence * 100)}% · {item.supporting_evidence_ids.length} supporting evidence
                    </small>
                  </article>
                ))}
              </div>
            </section>
          </div>

          <div className="agentic-grid">
            <section className="panel">
              <header className="panel-head">
                <div>
                  <p className="eyebrow">PROVENANCE</p>
                  <h2>Evidence bundle</h2>
                </div>
              </header>
              <div className="agentic-evidence">
                {report.evidence.map((item) => (
                  <article key={item.evidence_id}>
                    <span className="agentic-tier">{item.tier}</span>
                    <div>
                      <strong>{item.kind}</strong>
                      <p>{item.summary}</p>
                      <small>{item.evidence_id} · {item.source}</small>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel">
              <header className="panel-head">
                <div>
                  <p className="eyebrow">BUSINESS IMPACT</p>
                  <h2>Blast radius</h2>
                </div>
              </header>
              <div className="chip-list">
                {report.blast_radius.length > 0
                  ? report.blast_radius.map((asset) => <span key={asset}>{asset}</span>)
                  : <span>No downstream assets</span>}
              </div>
            </section>
          </div>

          <section className="panel agentic-remediation">
            <header className="panel-head">
              <div>
                <p className="eyebrow">GOVERNED MUTATION</p>
                <h2>Remediation & approval</h2>
              </div>
              <div className="panel-actions">
                {report.state === "AWAITING_APPROVAL" && !report.approved && (
                  <button onClick={() => void approve()} disabled={busy}>Approve plan</button>
                )}
                {report.state === "AWAITING_APPROVAL" && report.approved && (
                  <button onClick={() => void execute()} disabled={busy}>Execute approved recovery</button>
                )}
              </div>
            </header>

            {report.remediation ? (
              <div className="agentic-plan">
                <div>
                  <span>Action</span>
                  <strong>{report.remediation.action}</strong>
                </div>
                <div>
                  <span>Risk</span>
                  <strong>{report.remediation.risk}</strong>
                </div>
                <div>
                  <span>Approval</span>
                  <strong>{report.approved ? "APPROVED" : "REQUIRED"}</strong>
                </div>
                <div className="wide">
                  <span>Reason</span>
                  <p>{report.remediation.reason}</p>
                </div>
                <div className="wide">
                  <span>Rollback</span>
                  <p>{report.remediation.rollback}</p>
                </div>
              </div>
            ) : <p>No remediation proposed.</p>}
          </section>

          <div className="agentic-grid">
            <section className="panel">
              <header className="panel-head">
                <div>
                  <p className="eyebrow">STATE MACHINE</p>
                  <h2>Incident transitions</h2>
                </div>
              </header>
              <div className="agentic-transitions">
                {report.transitions.map((item, index) => (
                  <div key={item.to_state + "-" + index}>
                    <span>{item.from_state ?? "NEW"}</span>
                    <b>→</b>
                    <strong>{item.to_state}</strong>
                    <small>{item.reason}</small>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel">
              <header className="panel-head">
                <div>
                  <p className="eyebrow">INDEPENDENT GATES</p>
                  <h2>Verification</h2>
                </div>
              </header>
              <pre className="json-panel">{JSON.stringify(report.verification_result, null, 2)}</pre>
            </section>
          </div>

          <p className="agentic-mode-note">
            Mode: {report.mode}. Local proving-ground execution is deliberately separate from live Snowflake/Airflow validation.
          </p>
        </>
      )}
    </div>
  );
}
