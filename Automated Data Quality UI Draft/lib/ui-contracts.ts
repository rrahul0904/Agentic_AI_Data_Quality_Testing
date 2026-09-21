export function safeDisplayError(value: unknown, fallback = "Something went wrong"): string {
  if (typeof value === "string" && value.trim()) return value;
  if (value && typeof value === "object") {
    const item = value as Record<string, unknown>;
    const message = typeof item.message === "string" ? item.message : typeof item.detail === "string" ? item.detail : typeof item.error === "string" ? item.error : "";
    const kind = typeof item.error_type === "string" ? item.error_type.replaceAll("_", " ") : "";
    if (message) return kind ? `${kind}: ${message}` : message;
    try { return JSON.stringify(value) || fallback; } catch { return fallback; }
  }
  return fallback;
}

export function monitoringStatusLabel(value: unknown, fallback = "Not available"): string {
  const state = safeDisplayError(value, "Not available").toUpperCase();
  const labels: Record<string, string> = {
    QUEUED: "Queued", SUBMITTING: "Submitting", RUNNING: "Running", VERIFYING: "Verifying",
    MONITORING: "Waiting for observation", AWAITING_CONTINUATION: "Awaiting continuation", COMPLETED: "Completed", FAILED: "Failed",
    UNCERTAIN: "Uncertain — reconcile", OUTCOME_UNKNOWN: "Outcome unknown — reconcile", BLOCKED: "Blocked", PENDING: "Pending",
    NOT_RUN: "Not run", NOT_CHECKED: "Not checked", UNAVAILABLE: "Unavailable", SUBMITTED: "Submitted", PASSED: "Passed",
    VERIFIED: "Verified", AVAILABLE: "Available", STALE: "Stale — refresh needed",
  };
  return labels[state] ?? safeDisplayError(value, fallback);
}
