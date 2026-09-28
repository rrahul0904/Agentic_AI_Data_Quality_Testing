import assert from "node:assert/strict";
import test from "node:test";
import { actionMonitorDisplayStatus, isActiveActionState } from "../lib/action-monitor-status.ts";

test("external running and queued observations are visible while monitoring", () => {
  assert.equal(actionMonitorDisplayStatus("MONITORING", "RUNNING"), "RUNNING");
  assert.equal(actionMonitorDisplayStatus("MONITORING", "QUEUED"), "QUEUED");
});

test("a stale observation never overrides a terminal persisted run", () => {
  assert.equal(actionMonitorDisplayStatus("COMPLETED", "RUNNING"), "COMPLETED");
  assert.equal(actionMonitorDisplayStatus("RECOVERY_EXHAUSTED", "RUNNING"), "RECOVERY_EXHAUSTED");
});

test("only active actions keep Monitoring on a polling interval", () => {
  for (const state of ["QUEUED", "SUBMITTING", "RUNNING", "VERIFYING", "MONITORING", "AWAITING_CONTINUATION"]) {
    assert.equal(isActiveActionState(state), true, state);
  }
  for (const state of ["COMPLETED", "FAILED", "RECOVERY_EXHAUSTED", "CANCELLED", undefined]) {
    assert.equal(isActiveActionState(state), false, String(state));
  }
});
