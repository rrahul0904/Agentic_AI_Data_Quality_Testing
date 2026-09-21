import { currentWorkspaceState, hasCurrentWorkspaceAnalysis, hasCurrentWorkspacePlan, markCurrentWorkspaceStage, recordMatchesCurrentTable, resolveWorkspace, workspaceQuery } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

async function backend(endpoint: string, init?: RequestInit, timeoutMs = 30000): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${endpoint}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  const value = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : `ADE API returned ${response.status}`);
  return value;
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const currentState = await currentWorkspaceState(scope);
    if (!currentState.sourceTableScopeId) {
      return Response.json({ plan: null, capabilities: { status: "NO_ACTIVE_SCOPE" }, runs: [], revisions: [], schedules: [], requests: [], automationCapabilities: { status: "NO_ACTIVE_SCOPE" }, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
    }
    const project = workspaceQuery(scope);
    const incoming = new URL(request.url).searchParams;
    const runPage = Math.max(1, Number(incoming.get("run_page") ?? "1") || 1);
    const runPageSize = Math.max(1, Math.min(100, Number(incoming.get("run_page_size") ?? "10") || 10));
    const [capabilities, automationCapabilities] = await Promise.all([
      backend("/api/v1/quality-plans/capabilities"),
      backend("/api/v1/quality-automation/capabilities"),
    ]);
    if (!(await hasCurrentWorkspacePlan(scope))) {
      return Response.json({ plan: null, capabilities, runs: [], revisions: [], schedules: [], requests: [], automationCapabilities, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
    }
    let plan: Record<string, unknown> | null = null;
    let runs: unknown[] = [];
    let revisions: unknown[] = [];
    let schedules: unknown[] = [];
    let requests: unknown[] = [];
    try {
      const candidate = await backend(`/api/v1/quality-plans/latest?${project}`);
      if (!recordMatchesCurrentTable(candidate, currentState)) return Response.json({ plan: null, capabilities, runs: [], revisions: [], schedules: [], requests: [], automationCapabilities, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
      plan = candidate;
      const planId = String(plan.plan_id);
      const [history, revisionHistory, scheduleHistory, requestHistory] = await Promise.all([
        backend(`/api/v1/quality-plans/${String(plan.plan_id)}/runs?page=${runPage}&page_size=${runPageSize}`),
        backend(`/api/v1/quality-plans/${String(plan.plan_id)}/revisions`),
        backend(`/api/v1/quality-automation/schedules?plan_id=${encodeURIComponent(planId)}`),
        backend(`/api/v1/quality-automation/requests?plan_id=${encodeURIComponent(planId)}`),
      ]);
      runs = Array.isArray(history.items) ? history.items : [];
      revisions = Array.isArray(revisionHistory.items) ? revisionHistory.items : [];
      schedules = Array.isArray(scheduleHistory.items) ? scheduleHistory.items : [];
      requests = Array.isArray(requestHistory.items) ? requestHistory.items : [];
      return Response.json({
        plan, capabilities, runs, revisions, schedules, requests, automationCapabilities, workspace: scope,
        runPage: history.page ?? runPage, runPageSize: history.page_size ?? runPageSize,
        runTotal: history.total ?? runs.length, runHasNext: Boolean(history.has_next),
      }, { headers: { "Cache-Control": "no-store" } });
    } catch { /* A plan exists only after the operator generates it. */ }
    return Response.json({ plan, capabilities, runs, revisions, schedules, requests, automationCapabilities, workspace: scope, runPage, runPageSize, runTotal: 0, runHasNext: false }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load quality plans" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const body = await request.json() as Record<string, unknown>;
    const action = String(body.action || "");
    if (action === "generate") {
      if (!(await hasCurrentWorkspaceAnalysis(scope))) {
        return Response.json({ error: "Collect current connection and discovery evidence before generating a quality plan." }, { status: 409 });
      }
      const plan = await backend("/api/v1/quality-plans/generate", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ project_id: scope.projectId, environment: scope.environment }),
      }, 120000);
      await markCurrentWorkspaceStage(scope, "qualityPlanScopeId");
      return Response.json({ plan, runs: [] });
    }
    const planId = String(body.planId || "");
    if (!planId) return Response.json({ error: "planId is required" }, { status: 400 });
    if (action === "update") {
      const plan = await backend(`/api/v1/quality-plans/${encodeURIComponent(planId)}`, {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: body.name,
          checks: body.checks,
          add_checks: body.addChecks,
          remove_check_ids: body.removeCheckIds,
          changed_by: String(body.changedBy || "ui-operator"),
        }),
      });
      return Response.json({ plan });
    }
    if (action === "approve") {
      const plan = await backend(`/api/v1/quality-plans/${encodeURIComponent(planId)}/approve`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ approved_by: String(body.approvedBy || "ui-operator") }),
      });
      return Response.json({ plan });
    }
    if (action === "run") {
      const run = await backend(`/api/v1/quality-plans/${encodeURIComponent(planId)}/run`, { method: "POST" }, 300000);
      return Response.json({ run });
    }
    if (action === "runRule") {
      const checkId = String(body.checkId || "");
      if (!checkId) return Response.json({ error: "checkId is required" }, { status: 400 });
      const run = await backend(`/api/v1/quality-plans/${encodeURIComponent(planId)}/run`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ check_ids: [checkId] }),
      }, 300000);
      return Response.json({ run });
    }
    if (action === "queue") {
      const runRequest = await backend("/api/v1/quality-automation/requests", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          plan_id: planId, trigger_type: "MANUAL", trigger_ref: "ui-operator",
          idempotency_key: String(body.idempotencyKey || `manual:${crypto.randomUUID()}`),
          max_attempts: Number(body.maxAttempts || 1), timeout_seconds: Number(body.timeoutSeconds || 3600),
        }),
      });
      return Response.json({ request: runRequest });
    }
    if (action === "createSchedule") {
      const schedule = await backend("/api/v1/quality-automation/schedules", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          plan_id: planId, trigger_type: String(body.triggerType || "INTERVAL"),
          interval_minutes: body.intervalMinutes, event_name: body.eventName,
          enabled: true, created_by: "ui-operator",
        }),
      });
      return Response.json({ schedule });
    }
    if (action === "toggleSchedule") {
      const scheduleId = String(body.scheduleId || "");
      const schedule = await backend(`/api/v1/quality-automation/schedules/${encodeURIComponent(scheduleId)}`, {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: Boolean(body.enabled) }),
      });
      return Response.json({ schedule });
    }
    if (action === "cancelRequest") {
      const requestId = String(body.requestId || "");
      const runRequest = await backend(`/api/v1/quality-automation/requests/${encodeURIComponent(requestId)}/cancel`, { method: "POST" });
      return Response.json({ request: runRequest });
    }
    return Response.json({ error: "Unsupported quality-plan action" }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Quality-plan operation failed" }, { status: 502 });
  }
}
