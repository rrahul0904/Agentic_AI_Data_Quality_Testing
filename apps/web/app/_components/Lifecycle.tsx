"use client";

import type { Evidence, Lifecycle } from "./types";

type Props = { lifecycle: Lifecycle; evidence: Evidence[]; onEvidence?: (item: Evidence) => void };

export default function LifecycleView({ lifecycle, evidence, onEvidence }: Props) {
  const firstEvidence = evidence.find((item) => lifecycle.evidence_ids.includes(item.evidence_id));
  const steps = [
    { label: "Scheduled", at: lifecycle.scheduled_at, state: lifecycle.scheduled_at ? "observed" : "unknown" },
    { label: "Queued", at: lifecycle.queued_at, state: lifecycle.queued_at ? "observed" : "unknown", duration: lifecycle.queued_duration_seconds },
    { label: "Running", at: lifecycle.running_at, state: lifecycle.runtime_start_proven ? "observed" : "missing" },
    { label: "Operator started", at: lifecycle.operator_started_at, state: lifecycle.operator_start_proven ? "observed" : "missing" },
    { label: lifecycle.executor_state || lifecycle.metadata_state || "Terminal state", at: lifecycle.ended_at, state: "terminal" },
  ];
  return (
    <div className="lifecycle" aria-label={`Execution lifecycle for ${lifecycle.task_id}`}>
      {steps.map((step, index) => (
        <button key={`${step.label}-${index}`} className={`lifecycle-step ${step.state}`} onClick={() => firstEvidence && onEvidence?.(firstEvidence)} disabled={!firstEvidence}>
          <span className="lifecycle-node">{step.state === "missing" ? "×" : step.state === "unknown" ? "?" : ""}</span>
          <span className="lifecycle-copy"><strong>{step.label}</strong><small>{step.at ? new Date(step.at).toLocaleString() : step.state === "missing" ? "Not observed" : "Unknown"}</small></span>
          {step.duration != null && <span className="lifecycle-duration">{Math.round(step.duration)}s queued</span>}
        </button>
      ))}
    </div>
  );
}
