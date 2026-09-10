"use client";

import { useEffect, useMemo, useState } from "react";
import { getJson } from "../lib/api";

type UnresolvedCapability = {
  id: string;
  current: string;
  phase: string;
  reference: string;
  acceptance: string;
  known_limitation?: unknown;
};

type GoldenScenario = {
  id: string;
  title: string;
  expected: string;
  external_required: boolean;
  certification_track: string;
};

type ExactHeadEvidence = {
  head_sha?: string | null;
  local_ci_certified?: boolean;
  coco_parity_complete?: boolean;
  golden_scenarios?: {
    status?: string;
    passed?: number;
    failed?: number;
    head_sha?: string | null;
    evidence_fingerprint?: string | null;
  };
  certification_fingerprint?: string | null;
} | null;

type CertificationStatus = {
  status: string;
  benchmark: string;
  target_matrix_version?: string | null;
  capability_count: number;
  coco_capability_count: number;
  extension_capability_count: number;
  implemented_coco_count: number;
  unresolved_coco_count: number;
  coco_by_current: Record<string, number>;
  coco_by_phase: Record<string, number>;
  unresolved_coco_capabilities: UnresolvedCapability[];
  golden_scenario_definitions: GoldenScenario[];
  exact_head_evidence: ExactHeadEvidence;
  claims: {
    implementation_parity_ready: boolean;
    exact_head_ci_certified: boolean;
    live_external_certified: boolean;
    superiority_certified: boolean;
  };
  truthfulness: Record<string, boolean>;
  status_fingerprint: string;
};

function verdict(value: boolean, yes: string, no: string) {
  return <span className={value ? "status status-pass" : "status status-warn"}>{value ? yes : no}</span>;
}

function Metric({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return <article className="metric"><span>{label}</span><strong>{value}</strong>{sub && <small>{sub}</small>}</article>;
}

export default function CertificationConsole() {
  const [data, setData] = useState<CertificationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setBusy(true);
    try {
      setData(await getJson<CertificationStatus>("/api/v1/certification/coco"));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  const coverage = useMemo(() => {
    if (!data?.coco_capability_count) return 0;
    return Math.round((data.implemented_coco_count / data.coco_capability_count) * 1000) / 10;
  }, [data]);

  return (
    <div className="stack">
      <section className="panel">
        <header className="panel-head">
          <div>
            <p className="eyebrow">CANONICAL BENCHMARK · CLAIM BOUNDARIES</p>
            <h2>CoCo certification control room</h2>
          </div>
          <div className="panel-actions">
            <button className="ghost" disabled={busy} onClick={() => void refresh()}>{busy ? "Refreshing…" : "Refresh status"}</button>
          </div>
        </header>
        <p className="note">
          This surface keeps implementation coverage, exact-head CI, live external certification, and superiority separate. Missing evidence never becomes an inferred PASS.
        </p>
        {error && <div className="error-box">{error}</div>}
        {!data ? <div className="loading"><span className="spinner" />Loading certification evidence…</div> : <>
          <div className="metrics">
            <Metric label="CoCo coverage" value={`${coverage}%`} sub={`${data.implemented_coco_count}/${data.coco_capability_count} locally implemented`} />
            <Metric label="Unresolved" value={data.unresolved_coco_count} sub="canonical CoCo capabilities" />
            <Metric label="ADE extensions" value={data.extension_capability_count} sub="preserved outside parity gate" />
            <Metric label="Golden scenarios" value={data.golden_scenario_definitions.length} sub="deterministic scenario definitions" />
          </div>

          <div className="inline-summary">
            {verdict(data.claims.implementation_parity_ready, "Implementation ready", "Implementation incomplete")}
            {verdict(data.claims.exact_head_ci_certified, "Exact-head CI certified", "Exact-head CI not evidenced here")}
            {verdict(data.claims.live_external_certified, "Live external certified", "Live external not certified")}
            {verdict(data.claims.superiority_certified, "Superiority certified", "Superiority not certified")}
          </div>

          <div className="grid two-col">
            <section className="subpanel">
              <p className="eyebrow">CURRENT LEDGER STATE</p>
              <h3>Implementation distribution</h3>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>State</th><th>CoCo capabilities</th></tr></thead>
                  <tbody>{Object.entries(data.coco_by_current).map(([state, count]) => <tr key={state}><td><code>{state}</code></td><td>{count}</td></tr>)}</tbody>
                </table>
              </div>
            </section>
            <section className="subpanel">
              <p className="eyebrow">EXACT-HEAD EVIDENCE</p>
              <h3>Last materialized certification report</h3>
              {data.exact_head_evidence ? <dl className="detail-list">
                <div><dt>Head SHA</dt><dd><code>{data.exact_head_evidence.head_sha ?? "unknown"}</code></dd></div>
                <div><dt>Golden status</dt><dd>{data.exact_head_evidence.golden_scenarios?.status ?? "unknown"}</dd></div>
                <div><dt>Passed / failed</dt><dd>{data.exact_head_evidence.golden_scenarios?.passed ?? "—"} / {data.exact_head_evidence.golden_scenarios?.failed ?? "—"}</dd></div>
                <div><dt>Fingerprint</dt><dd><code>{data.exact_head_evidence.certification_fingerprint ?? "—"}</code></dd></div>
              </dl> : <div className="empty">No checked-in exact-head report is present. CI artifacts remain the authoritative run evidence.</div>}
            </section>
          </div>
        </>}
      </section>

      {data && <section className="panel">
        <header className="panel-head"><div><p className="eyebrow">REMAINING ACCEPTANCE WORK</p><h2>Unresolved CoCo capabilities</h2></div><span className="status status-warn">{data.unresolved_coco_count} open</span></header>
        {data.unresolved_coco_capabilities.length === 0 ? <div className="empty">No unresolved implementation entries in the canonical CoCo track.</div> : <div className="table-wrap">
          <table>
            <thead><tr><th>Capability</th><th>Phase</th><th>State</th><th>Acceptance boundary</th></tr></thead>
            <tbody>{data.unresolved_coco_capabilities.map((item) => <tr key={item.id}><td><strong>{item.reference || item.id}</strong><br /><code>{item.id}</code></td><td>{item.phase}</td><td><span className="status status-warn">{item.current}</span></td><td>{item.acceptance}</td></tr>)}</tbody>
          </table>
        </div>}
      </section>}

      {data && <section className="panel">
        <header className="panel-head"><div><p className="eyebrow">DETERMINISTIC RELEASE PROVING GROUND</p><h2>Eight golden scenarios</h2></div></header>
        <div className="card-grid">{data.golden_scenario_definitions.map((scenario) => <article className="mini-card" key={scenario.id}><span>{scenario.id}</span><strong>{scenario.title}</strong><small>{scenario.certification_track.replaceAll("_", " ")} · expected {scenario.expected}</small></article>)}</div>
        <div className="inline-summary"><code>status fingerprint: {data.status_fingerprint}</code></div>
      </section>}
    </div>
  );
}
