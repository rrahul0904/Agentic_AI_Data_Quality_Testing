import { currentWorkspaceState, recordMatchesCurrentTable, resolveWorkspace, workspaceQuery } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

function backendHeaders(request: Request | undefined, init: RequestInit | undefined, projectId: string): Headers {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  // Forward only the explicit ADE headers. The browser never receives a
  // backend secret; deployments may instead inject ADE_UI_API_KEY server-side.
  const incoming = request?.headers;
  for (const name of ["x-ade-api-key", "x-ade-identity", "x-ade-project-id", "x-ade-environment"]) {
    const value = incoming?.get(name) ?? (name === "x-ade-api-key" ? process.env.ADE_UI_API_KEY : undefined);
    if (value) headers.set(name, value);
  }
  headers.set("x-ade-project-id", projectId);
  return headers;
}

async function backend(endpoint: string, projectId: string, init?: RequestInit, timeoutMs = 120000, request?: Request): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${endpoint}`, { ...init, headers: backendHeaders(request, init, projectId), cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  const body = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `ADE API returned ${response.status}`);
  return body;
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const currentState = await currentWorkspaceState(scope);
    const query = workspaceQuery(scope);
    const requestedRunId = new URL(request.url).searchParams.get("run_id");
    const [capabilities, plans, runs] = await Promise.all([
      backend(`/api/v1/actions/capabilities?${query}`, scope.projectId, undefined, 120000, request),
      backend(`/api/v1/actions/plans?${query}`, scope.projectId, undefined, 120000, request),
      requestedRunId
        ? backend(`/api/v1/actions/runs/${encodeURIComponent(requestedRunId)}?${query}`, scope.projectId, undefined, 120000, request).then((run) => ({ items: [run], count: 1, total: 1 }))
        : backend(`/api/v1/actions/runs?${query}`, scope.projectId, undefined, 120000, request),
    ]);
    if (requestedRunId) {
      const runItems = Array.isArray(runs.items) ? runs.items : [];
      const selected = runItems[0];
      const plan = selected && typeof selected === "object" && selected.plan && typeof selected.plan === "object" ? selected.plan as Record<string, unknown> : null;
      if (!selected || plan?.project_id !== scope.projectId || String(plan.environment ?? "").toLowerCase() !== scope.environment.toLowerCase()) {
        return Response.json({ error: "The requested run is outside the active project and environment scope." }, { status: 404 });
      }
      return Response.json({ capabilities, plans: { ...plans, items: [] }, runs, workspace: scope, source_table_scope_id: currentState.sourceTableScopeId || null }, { headers: { "Cache-Control": "no-store" } });
    }
    const items = Array.isArray(plans.items)
      ? (currentState.selectedAssetIdentity ? plans.items.filter((item) => recordMatchesCurrentTable(item, currentState)) : plans.items)
      : [];
    const runItems = Array.isArray(runs.items)
      ? (currentState.selectedAssetIdentity
        ? runs.items.filter((item) => item && typeof item === "object" && recordMatchesCurrentTable((item as Record<string, unknown>).plan ?? item, currentState))
        : runs.items)
      : [];
    return Response.json({ capabilities, plans: { ...plans, items, count: items.length }, runs: { ...runs, items: runItems, count: runItems.length }, workspace: scope, source_table_scope_id: currentState.sourceTableScopeId || null }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load governed actions" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const currentState = await currentWorkspaceState(scope);
    const body = await request.json() as Record<string, unknown>;
    const action = String(body.action ?? "");
    if (action === "plan") {
      if (body.operationKind === "quality_checks" && !currentState.selectedAssetIdentity) {
        throw new Error("Quality checks require a selected source table. Independent Airflow, dbt, COPY, and Snowpipe jobs do not.");
      }
      return Response.json(await backend("/api/v1/actions/plan-from-intent", scope.projectId, {
        method: "POST",
        body: JSON.stringify({
          project_id: scope.projectId,
          environment: scope.environment,
          intent: body.intent,
          target_asset: body.targetAsset || body.requestedTarget || null,
          mode: body.mode || null,
          operation_kind: body.operationKind || null,
          selected_asset_id: currentState.sourceTableScopeId || null,
        }),
      }, 120000, request));
    }
    if (action === "status") {
      const runId = encodeURIComponent(String(body.runId ?? ""));
      if (!body.runId) throw new Error("A monitored action run is required.");
      return Response.json(await backend(`/api/v1/actions/runs/${runId}?${workspaceQuery(scope)}`, scope.projectId, undefined, 120000, request));
    }
    const planId = encodeURIComponent(String(body.planId ?? ""));
    if (!body.planId) throw new Error("A persisted action plan is required.");
    const currentPlans = await backend(`/api/v1/actions/plans?${workspaceQuery(scope)}`, scope.projectId, undefined, 120000, request);
    const belongsToCurrentWorkflow = Array.isArray(currentPlans.items)
      && currentPlans.items.some((item) => item && typeof item === "object" && (item as Record<string, unknown>).plan_id === body.planId
        && (!currentState.selectedAssetIdentity || recordMatchesCurrentTable(item, currentState)));
    if (!belongsToCurrentWorkflow) return Response.json({ error: "This action plan belongs to a different workflow or source-table scope." }, { status: 404 });
    if (action === "dry-run") {
      return Response.json(await backend(`/api/v1/actions/plans/${planId}/dry-run`, scope.projectId, {
        method: "POST",
        body: JSON.stringify({ idempotency_key: `ui-dry-${crypto.randomUUID()}` }),
      }, 120000, request));
    }
    if (action === "approve") {
      return Response.json(await backend(`/api/v1/actions/plans/${planId}/approve`, scope.projectId, {
        method: "POST",
        body: JSON.stringify({ ttl_minutes: 15 }),
      }, 120000, request));
    }
    if (action === "reject") {
      return Response.json(await backend(`/api/v1/actions/plans/${planId}/reject`, scope.projectId, {
        method: "POST",
        body: JSON.stringify({ reason: body.reason }),
      }, 120000, request));
    }
    if (action === "execute") {
      if (!body.approvalId) throw new Error("An exact human approval is required.");
      return Response.json(await backend(`/api/v1/actions/plans/${planId}/execute`, scope.projectId, {
        method: "POST",
        body: JSON.stringify({ idempotency_key: `ui-exec-${crypto.randomUUID()}`, approval_id: body.approvalId }),
      }, 3600000, request));
    }
    if (action === "resume") {
      const runId = encodeURIComponent(String(body.runId ?? ""));
      if (!body.runId) throw new Error("A monitored action run is required.");
      return Response.json(await backend(`/api/v1/actions/runs/${runId}/resume?${workspaceQuery(scope)}`, scope.projectId, { method: "POST" }, 120000, request));
    }
    if (action === "reconcile") {
      const runId = encodeURIComponent(String(body.runId ?? ""));
      if (!body.runId) throw new Error("An uncertain action run is required.");
      return Response.json(await backend(`/api/v1/actions/runs/${runId}/reconcile?${workspaceQuery(scope)}`, scope.projectId, { method: "POST" }, 120000, request));
    }
    if (action === "verify") {
      const runId = encodeURIComponent(String(body.runId ?? ""));
      if (!body.runId) throw new Error("A completed action run is required.");
      return Response.json(await backend(`/api/v1/actions/runs/${runId}/verify?${workspaceQuery(scope)}`, scope.projectId, { method: "POST" }, 120000, request));
    }
    throw new Error("Unsupported governed action.");
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Governed action failed" }, { status: 502 });
  }
}
