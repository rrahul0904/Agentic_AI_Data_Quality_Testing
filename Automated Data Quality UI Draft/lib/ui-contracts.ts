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

export type IntegrationConnectionState = "PASSING" | "ATTENTION" | "UNKNOWN";

/**
 * Normalize provider metadata for the Overview connection summary.  dbt's
 * state endpoint uses EXECUTION_EVIDENCE_FOUND when the local project and
 * artifacts are available; that is a successful readiness signal, not a
 * failed connection.
 */
export function integrationConnectionState(value: Record<string, unknown>): IntegrationConnectionState {
  const raw = safeDisplayError(value.connection_status ?? value.status ?? value.execution_status ?? "UNKNOWN").toUpperCase();
  if (["CONNECTED", "PASS", "PASSED", "AVAILABLE", "HEALTHY", "READY", "EXECUTION_EVIDENCE_FOUND"].includes(raw)) return "PASSING";
  if (["ERROR", "FAIL", "FAILED", "SKIP_EXTERNAL", "UNAVAILABLE", "BLOCKED"].includes(raw)) return "ATTENTION";
  return "UNKNOWN";
}

/**
 * AI lineage verification is an optional review action.  A missing review is
 * not an outage and must not be presented as one.
 */
export function aiReviewStatusLabel(status?: string, busy = false, availability?: string): string {
  if (busy) return "Running";
  const normalized = status?.toUpperCase();
  if (normalized === "COMPLETED") return "Completed";
  if (normalized === "NEEDS_HUMAN_APPROVAL") return "Needs approval";
  if (normalized === "ERROR" || normalized === "FAILED") return "Failed";
  if (["DISABLED", "UNAVAILABLE", "NOT_CONFIGURED"].includes(normalized || "")) {
    return ["READY", "CONFIGURED"].includes(String(availability || "").toUpperCase()) ? "Not run" : "Unavailable";
  }
  return "Not run";
}

export function aiReviewStatusDescription(hasReview: boolean, availability?: string): string {
  if (hasReview) return "Optional review recorded; deterministic results remain the source of truth.";
  return ["READY", "CONFIGURED"].includes(String(availability || "").toUpperCase())
    ? "Optional review has not been requested."
    : "AI review is unavailable; deterministic results remain available.";
}
