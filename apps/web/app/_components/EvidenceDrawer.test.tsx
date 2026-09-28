import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EvidenceDrawer from "./EvidenceDrawer";

describe("EvidenceDrawer", () => {
  it("shows normalized evidence and closes", () => {
    const close = vi.fn();
    render(<EvidenceDrawer evidence={{ evidence_id: "ev-1", tier: "T2", kind: "runtime_state", source: "airflow", summary: "Task remained queued", payload: { metadata_state: "QUEUED" }, created_at: "2026-09-09T22:43:51Z" }} onClose={close} />);
    expect(screen.getByText("Task remained queued")).toBeTruthy();
    expect(screen.getByText(/QUEUED/)).toBeTruthy();
    expect(screen.getByText(/untrusted evidence/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Close evidence drawer"));
    expect(close).toHaveBeenCalledOnce();
  });
});
