"use client";

import { useEffect, useMemo, useState } from "react";
import { getJson, postJson } from "../../lib/api";
import styles from "./prototype.module.css";

type Overview = {
  mode: string;
  project: string;
  health_score: number;
  health_status: string;
  counts: {
    sources: number;
    airflow_dags: number;
    dbt_models: number;
    dbt_tests: number;
    tools: number;
  };
  findings: Array<{ severity: string; source: string; title: string; detail: string }>;
};

type Scenario = {
  scenario_id: string;
  title: string;
  affected_asset: string;
};

type Remediation = {
  action: string;
  reason: string;
  risk: string;
  rollback: string;
  requires_approval: boolean;
  status?: string;
  approved_by?: string | null;
  arguments?: {
    selective_recovery?: {
      airflow_actions?: Array<{
        system: string;
        operation: string;
        target: string;
        risk: string;
      }>;
      dbt_command?: string | null;
      quality_rechecks?: string[];
      certification_targets?: string[];
    };
  };
};

type Incident = {
  incident_id: string;
  scenario_id: string;
  title?: string;
  affected_asset?: string;
  state: string;
  mode: string;
  first_divergence: string | null;
  root_cause: string | null;
  root_cause_confidence: number;
  certification: string;
  approved: boolean;
  blast_radius?: string[];
  evidence?: Array<{ evidence_id: string; kind: string; source: string; summary: string }>;
  remediation?: Remediation | null;
  verification_result?: Record<string, unknown>;
};

type ScenarioResponse = { scenarios: Scenario[] };
type IncidentListResponse = { incidents: Incident[] };

const terminalStates = new Set(["RESOLVED", "BLOCKED", "FAILED"]);

function confidenceLabel(value: number): string {
  if (value >= 0.9) return "High confidence";
  if (value >= 0.7) return "Medium confidence";
  return "Developing confidence";
}

function stateLabel(state: string): string {
  return state.replaceAll("_", " ");
}

function remediationSteps(remediation: Remediation): string[] {
  const recovery = remediation.arguments?.selective_recovery;
  const steps: string[] = [];
  for (const action of recovery?.airflow_actions || []) {
    steps.push(`${action.system}: ${action.operation} ${action.target}`);
  }
  if (recovery?.dbt_command) steps.push(`dbt: ${recovery.dbt_command}`);
  for (const check of recovery?.quality_rechecks || []) steps.push(`Recheck quality: ${check}`);
  for (const target of recovery?.certification_targets || []) steps.push(`Recertify: ${target}`);
  if (!steps.length) steps.push(remediation.action);
  return steps;
}

export default function PrototypeConsole() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [activeIncident, setActiveIncident] = useState<Incident | null>(null);
  const [selectedScenario, setSelectedScenario] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setError(null);
    try {
      const [nextOverview, nextScenarios, nextIncidents] = await Promise.all([
        getJson<Overview>("/api/v1/overview"),
        getJson<ScenarioResponse>("/api/v1/investigations/scenarios"),
        getJson<IncidentListResponse>("/api/v1/investigations?limit=12"),
      ]);
      setOverview(nextOverview);
      setScenarios(nextScenarios.scenarios || []);
      setIncidents(nextIncidents.incidents || []);
      if (!selectedScenario && nextScenarios.scenarios?.length) {
        setSelectedScenario(nextScenarios.scenarios[0].scenario_id);
      }
      if (activeIncident) {
        const refreshed = await getJson<Incident>(`/api/v1/investigations/${activeIncident.incident_id}`);
        setActiveIncident(refreshed);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Prototype data is unavailable");
    }
  }

  useEffect(() => {
    void refresh();
    // The initial load is intentionally one-shot; subsequent refreshes are operator-driven.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startScenario() {
    if (!selectedScenario) return;
    setBusy("start");
    setError(null);
    try {
      const incident = await postJson<Incident>(`/api/v1/investigations/${selectedScenario}/start`, {});
      setActiveIncident(incident);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to start investigation");
    } finally {
      setBusy(null);
    }
  }

  async function openIncident(incidentId: string) {
    setBusy(`open:${incidentId}`);
    setError(null);
    try {
      setActiveIncident(await getJson<Incident>(`/api/v1/investigations/${incidentId}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load investigation");
    } finally {
      setBusy(null);
    }
  }

  async function approveIncident() {
    if (!activeIncident) return;
    setBusy("approve");
    setError(null);
    try {
      await postJson(`/api/v1/investigations/${activeIncident.incident_id}/approve`, {
        approved_by: "prototype-operator",
      });
      setActiveIncident(await getJson<Incident>(`/api/v1/investigations/${activeIncident.incident_id}`));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Approval failed");
    } finally {
      setBusy(null);
    }
  }

  async function executeIncident() {
    if (!activeIncident) return;
    setBusy("execute");
    setError(null);
    try {
      const result = await postJson<Incident>(`/api/v1/investigations/${activeIncident.incident_id}/execute`, {});
      setActiveIncident(result);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Execution failed");
    } finally {
      setBusy(null);
    }
  }

  const selectedScenarioDetails = useMemo(
    () => scenarios.find((item) => item.scenario_id === selectedScenario),
    [scenarios, selectedScenario],
  );

  const nextAction = useMemo(() => {
    if (!activeIncident) return "Start a guided investigation";
    if (activeIncident.state === "AWAITING_APPROVAL") return "Review evidence and approve the remediation";
    if (activeIncident.approved && !terminalStates.has(activeIncident.state)) return "Execute the approved remediation";
    if (activeIncident.state === "RESOLVED") return "Review the certification receipt";
    return "Review the investigation evidence";
  }, [activeIncident]);

  return (
    <main className={styles.shell}>
      <section className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>ADE PROTOTYPE 1.0</p>
          <h1>Agentic Data Engineering Workbench</h1>
          <p className={styles.subtitle}>
            Understand a data project, investigate a failure, review grounded evidence, approve a remediation, and verify the result.
          </p>
        </div>
        <div className={styles.heroActions}>
          <button className={styles.secondaryButton} onClick={() => void refresh()} disabled={busy !== null}>
            Refresh
          </button>
          <a className={styles.textLink} href="/">Open full operator console</a>
        </div>
      </section>

      {error ? <div className={styles.errorBanner}>{error}</div> : null}

      <section className={styles.metrics} aria-label="Project intelligence">
        <article className={styles.metricCard}>
          <span>Health</span>
          <strong>{overview ? `${overview.health_score}%` : "—"}</strong>
          <small>{overview?.health_status || "Loading project health"}</small>
        </article>
        <article className={styles.metricCard}>
          <span>dbt</span>
          <strong>{overview?.counts.dbt_models ?? "—"}</strong>
          <small>{overview ? `${overview.counts.dbt_tests} tests discovered` : "Loading"}</small>
        </article>
        <article className={styles.metricCard}>
          <span>Airflow</span>
          <strong>{overview?.counts.airflow_dags ?? "—"}</strong>
          <small>orchestration workflows</small>
        </article>
        <article className={styles.metricCard}>
          <span>Agent tools</span>
          <strong>{overview?.counts.tools ?? "—"}</strong>
          <small>governed capabilities</small>
        </article>
      </section>

      <section className={styles.grid}>
        <article className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.kicker}>1 · START</p>
              <h2>Choose a guided failure scenario</h2>
            </div>
            <span className={styles.badge}>{overview?.mode || "Loading"}</span>
          </div>

          <label className={styles.label} htmlFor="scenario">Scenario</label>
          <select
            id="scenario"
            className={styles.select}
            value={selectedScenario}
            onChange={(event) => setSelectedScenario(event.target.value)}
          >
            {scenarios.map((scenario) => (
              <option key={scenario.scenario_id} value={scenario.scenario_id}>
                {scenario.title}
              </option>
            ))}
          </select>

          {selectedScenarioDetails ? (
            <div className={styles.scenarioSummary}>
              <strong>{selectedScenarioDetails.title}</strong>
              <span>Affected asset: {selectedScenarioDetails.affected_asset}</span>
            </div>
          ) : null}

          <button className={styles.primaryButton} onClick={() => void startScenario()} disabled={!selectedScenario || busy !== null}>
            {busy === "start" ? "Investigating…" : "Start agent investigation"}
          </button>

          <div className={styles.workflow}>
            {[
              "Detect",
              "Collect evidence",
              "Root cause",
              "Impact",
              "Propose fix",
              "Approval",
              "Execute",
              "Verify",
            ].map((step) => <span key={step}>{step}</span>)}
          </div>
        </article>

        <article className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.kicker}>2 · INVESTIGATE</p>
              <h2>Evidence-backed RCA</h2>
            </div>
            {activeIncident ? <span className={styles.badge}>{stateLabel(activeIncident.state)}</span> : null}
          </div>

          {!activeIncident ? (
            <div className={styles.emptyState}>
              <strong>No active investigation</strong>
              <span>Start a scenario or open a recent incident.</span>
            </div>
          ) : (
            <div className={styles.investigation}>
              <div className={styles.investigationHeadline}>
                <div>
                  <span className={styles.muted}>Incident</span>
                  <strong>{activeIncident.incident_id}</strong>
                </div>
                <div>
                  <span className={styles.muted}>Certification</span>
                  <strong>{activeIncident.certification}</strong>
                </div>
              </div>

              <div className={styles.rcaBlock}>
                <span className={styles.muted}>Root cause</span>
                <strong>{activeIncident.root_cause || "Agents are still establishing the root cause"}</strong>
                <small>
                  {confidenceLabel(activeIncident.root_cause_confidence || 0)} · {Math.round((activeIncident.root_cause_confidence || 0) * 100)}%
                </small>
              </div>

              <div>
                <span className={styles.muted}>First divergence</span>
                <p>{activeIncident.first_divergence || "Not established yet"}</p>
              </div>

              <div>
                <span className={styles.muted}>Blast radius</span>
                <div className={styles.chips}>
                  {(activeIncident.blast_radius || []).length
                    ? activeIncident.blast_radius?.map((asset) => <span key={asset}>{asset}</span>)
                    : <span>Pending impact analysis</span>}
                </div>
              </div>

              <div>
                <span className={styles.muted}>Evidence</span>
                <div className={styles.evidenceList}>
                  {(activeIncident.evidence || []).slice(0, 5).map((item) => (
                    <div key={item.evidence_id}>
                      <strong>{item.kind}</strong>
                      <span>{item.summary}</span>
                      <small>{item.source}</small>
                    </div>
                  ))}
                  {!activeIncident.evidence?.length ? <p>No evidence surfaced yet.</p> : null}
                </div>
              </div>
            </div>
          )}
        </article>
      </section>

      <section className={styles.grid}>
        <article className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.kicker}>3 · GOVERN</p>
              <h2>Human approval boundary</h2>
            </div>
          </div>
          <p className={styles.nextAction}>{nextAction}</p>
          {activeIncident?.remediation ? (
            <div className={styles.remediation}>
              <strong>{activeIncident.remediation.action}</strong>
              <p>{activeIncident.remediation.reason}</p>
              <div className={styles.chips}>
                <span>Risk: {activeIncident.remediation.risk}</span>
                <span>{activeIncident.remediation.requires_approval ? "Approval required" : "Read-only"}</span>
                {activeIncident.remediation.status ? <span>{activeIncident.remediation.status}</span> : null}
              </div>
              {remediationSteps(activeIncident.remediation).map((step, index) => (
                <div key={`${step}-${index}`}>
                  <span>{index + 1}</span>
                  <p>{step}</p>
                </div>
              ))}
              <small className={styles.muted}>Rollback: {activeIncident.remediation.rollback}</small>
            </div>
          ) : (
            <div className={styles.emptyState}>No remediation proposal is available yet.</div>
          )}

          <div className={styles.actionRow}>
            <button
              className={styles.primaryButton}
              onClick={() => void approveIncident()}
              disabled={!activeIncident || activeIncident.state !== "AWAITING_APPROVAL" || busy !== null}
            >
              {busy === "approve" ? "Approving…" : "Approve remediation"}
            </button>
            <button
              className={styles.secondaryButton}
              onClick={() => void executeIncident()}
              disabled={!activeIncident || !activeIncident.approved || terminalStates.has(activeIncident.state) || busy !== null}
            >
              {busy === "execute" ? "Executing…" : "Execute + verify"}
            </button>
          </div>
        </article>

        <article className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.kicker}>4 · VERIFY</p>
              <h2>Recent investigation receipts</h2>
            </div>
          </div>
          <div className={styles.incidentList}>
            {incidents.slice(0, 7).map((incident) => (
              <button key={incident.incident_id} onClick={() => void openIncident(incident.incident_id)} disabled={busy !== null}>
                <div>
                  <strong>{incident.scenario_id}</strong>
                  <span>{incident.incident_id}</span>
                </div>
                <div className={styles.incidentState}>
                  <span>{stateLabel(incident.state)}</span>
                  <small>{incident.certification}</small>
                </div>
              </button>
            ))}
            {!incidents.length ? <div className={styles.emptyState}>No investigation receipts yet.</div> : null}
          </div>
        </article>
      </section>

      <section className={styles.readiness}>
        <div>
          <p className={styles.kicker}>CLOUD PROTOTYPE BOUNDARY</p>
          <h2>What this slice proves</h2>
          <p>
            The browser-to-API investigation journey is now isolated as a product flow. Cloud-native persistence remains a separate bounded migration because the certified backend currently constructs SQLite-backed control-plane and investigation stores directly.
          </p>
        </div>
        <div className={styles.readinessGrid}>
          <span><b>Ready</b> Web/API proxy</span>
          <span><b>Ready</b> Guided investigations</span>
          <span><b>Ready</b> Approval boundary</span>
          <span><b>Ready</b> Verification receipts</span>
          <span><b>Next</b> Postgres persistence adapter</span>
          <span><b>Next</b> Object artifact storage</span>
        </div>
      </section>
    </main>
  );
}
