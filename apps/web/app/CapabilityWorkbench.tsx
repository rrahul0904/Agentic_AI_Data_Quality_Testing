"use client";

import { useEffect, useMemo, useState } from "react";
import { getJson, postJson } from "../lib/api";

type OperationMeta = {
  tool: string;
  risk: string;
  capability: string;
};

type DomainSurface = Record<string, Record<string, OperationMeta>>;

type Props = {
  domain: string;
  title: string;
  eyebrow: string;
  description: string;
  defaultArgs?: Record<string, unknown>;
};

export default function CapabilityWorkbench({
  domain,
  title,
  eyebrow,
  description,
  defaultArgs = {},
}: Props) {
  const [surface, setSurface] = useState<Record<string, OperationMeta>>({});
  const [operation, setOperation] = useState("");
  const [argsText, setArgsText] = useState(JSON.stringify(defaultArgs, null, 2));
  const [actorMode, setActorMode] = useState("analyst");
  const [interactionMode, setInteractionMode] = useState("agent");
  const [environment, setEnvironment] = useState("dev");
  const [approved, setApproved] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getJson<DomainSurface>("/api/v1/domains")
      .then((domains) => {
        if (cancelled) return;
        const operations = domains[domain] ?? {};
        setSurface(operations);
        const first = Object.keys(operations)[0] ?? "";
        setOperation((current) => current || first);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => { cancelled = true; };
  }, [domain]);

  const selected = useMemo(() => surface[operation], [operation, surface]);
  const mutating = selected?.risk === "mutating" || selected?.risk === "destructive";

  async function invoke() {
    if (!operation) return;
    setBusy(true);
    setError(null);
    try {
      let args: Record<string, unknown> = {};
      if (argsText.trim()) {
        const parsed = JSON.parse(argsText);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Arguments must be a JSON object.");
        }
        args = parsed as Record<string, unknown>;
      }
      const response = await postJson<unknown>("/api/v1/" + domain + "/" + operation, {
        args,
        actor_mode: actorMode,
        interaction_mode: interactionMode,
        environment,
        dry_run: dryRun,
        approved,
      });
      setResult(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <header className="panel-head">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>
        {selected && (
          <div className="chip-list">
            <span>{selected.capability}</span>
            <span className={mutating ? "chip-muted" : "chip-good"}>{selected.risk}</span>
          </div>
        )}
      </header>

      <p className="note">{description}</p>

      <div className="capability-workbench">
        <div className="capability-controls">
          <label>
            Operation
            <select value={operation} onChange={(event) => {
              setOperation(event.target.value);
              setApproved(false);
              setResult(null);
            }}>
              {Object.entries(surface).map(([name, meta]) => (
                <option key={name} value={name}>
                  {name} · {meta.capability} · {meta.risk}
                </option>
              ))}
            </select>
          </label>

          <label>
            Actor mode
            <select value={actorMode} onChange={(event) => setActorMode(event.target.value)}>
              <option value="analyst">Analyst</option>
              <option value="ask">Ask</option>
              <option value="plan">Plan</option>
              <option value="builder">Builder</option>
              <option value="admin">Admin</option>
            </select>
          </label>

          <label>
            Interaction mode
            <select value={interactionMode} onChange={(event) => {
              setInteractionMode(event.target.value);
              setApproved(false);
              setResult(null);
            }}>
              <option value="agent">Agent</option>
              <option value="plan">Plan</option>
              <option value="ask">Ask</option>
              <option value="edit">Edit</option>
              <option value="code">Code</option>
            </select>
          </label>

          <label>
            Environment
            <select value={environment} onChange={(event) => setEnvironment(event.target.value)}>
              <option value="dev">Dev</option>
              <option value="staging">Staging</option>
              <option value="prod">Prod</option>
            </select>
          </label>

          <label className="capability-toggle">
            <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
            Dry run
          </label>

          <label className="capability-toggle">
            <input
              type="checkbox"
              checked={approved}
              disabled={!mutating}
              onChange={(event) => setApproved(event.target.checked)}
            />
            Explicit approval
          </label>
        </div>

        <label className="capability-args">
          Arguments
          <textarea
            spellCheck={false}
            value={argsText}
            onChange={(event) => setArgsText(event.target.value)}
            placeholder={'{"target": ".", "query": "reservations"}'}
          />
        </label>

        <div className="inline-summary">
          <button className="primary" onClick={() => void invoke()} disabled={busy || !operation}>
            {busy ? "Running…" : dryRun ? "Run dry check" : "Invoke governed tool"}
          </button>
          {mutating && !approved && <span>Mutation remains blocked until explicitly approved.</span>}
          {!mutating && <span>Read-only operation; no approval escalation is applied.</span>}
          <span>Interaction policy: {interactionMode} · actor authorization: {actorMode}.</span>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {result !== null && (
        <pre className="json-panel tall-json">{JSON.stringify(result, null, 2)}</pre>
      )}
    </section>
  );
}
