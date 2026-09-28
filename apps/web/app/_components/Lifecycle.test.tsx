import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LifecycleView from "./Lifecycle";
import type { Evidence, Lifecycle } from "./types";

const evidence: Evidence = {
  evidence_id: "ev-1", tier: "T1", kind: "task_state_event", source: "airflow",
  summary: "Executor reported FAILED while metadata remained QUEUED", payload: {}, created_at: "2026-09-09T22:43:51Z",
};

const lifecycle: Lifecycle = {
  task_id: "load_properties.determine_window", run_id: "run-1", dag_id: "ingest_reference_data",
  queued_at: "2026-09-09T22:33:41Z", ended_at: "2026-09-09T22:43:51Z",
  metadata_state: "QUEUED", executor_state: "FAILED", runtime_start_proven: false,
  operator_start_proven: false, task_log_exists: false, queued_duration_seconds: 610,
  evidence_ids: ["ev-1"],
};

describe("LifecycleView", () => {
  it("renders missing runtime and operator transitions independently of color", () => {
    render(<LifecycleView lifecycle={lifecycle} evidence={[evidence]} />);
    expect(screen.getByText("Queued")).toBeTruthy();
    expect(screen.getByText("610s queued")).toBeTruthy();
    expect(screen.getAllByText("Not observed")).toHaveLength(2);
    expect(screen.getByText("FAILED")).toBeTruthy();
  });

  it("opens supporting evidence from a lifecycle event", () => {
    const onEvidence = vi.fn();
    render(<LifecycleView lifecycle={lifecycle} evidence={[evidence]} onEvidence={onEvidence} />);
    fireEvent.click(screen.getByText("Queued"));
    expect(onEvidence).toHaveBeenCalledWith(evidence);
  });
});
