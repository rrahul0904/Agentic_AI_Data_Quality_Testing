/** Present the last correlated external observation without changing the persisted run state. */
export function actionMonitorDisplayStatus(runState: string | undefined, runtimeState: string | undefined): string {
  const observed = String(runtimeState || "").toUpperCase();
  if (runState === "MONITORING" && ["RUNNING", "QUEUED", "SCHEDULED", "DEFERRED"].includes(observed)) return observed;
  return runState || "NOT_CHECKED";
}

/** Terminal history can stay open without keeping the API in a polling loop. */
export function isActiveActionState(state: string | undefined): boolean {
  return ["QUEUED", "SUBMITTING", "RUNNING", "VERIFYING", "MONITORING", "AWAITING_CONTINUATION"].includes(String(state || "").toUpperCase());
}
