import { resolveWorkspace, workspaceQuery } from "../../../../../lib/server-workspace";
import { isPhase4Fixture, phase4RunDetail } from "../../../../../lib/server-test-fixture";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

export async function GET(request: Request, context: { params: Promise<{ runId: string }> }) {
  try {
    const { runId: requestedRunId } = await context.params;
    if (isPhase4Fixture(request)) {
      const detail = await phase4RunDetail(requestedRunId);
      return detail ? Response.json(detail, { headers: { "Cache-Control": "no-store", "X-ADQ-Test-Fixture": "phase4" } }) : Response.json({ error: "Fixture run not found" }, { status: 404 });
    }
    const scope = await resolveWorkspace(request);
    const runId = requestedRunId;
    const planId = new URL(request.url).searchParams.get("plan_id");
    if (!planId) return Response.json({ error: "plan_id is required" }, { status: 400 });
    const response = await fetch(
      `${API_BASE}/api/v1/quality-plans/${encodeURIComponent(planId)}/runs/${encodeURIComponent(runId)}?${workspaceQuery(scope)}`,
      { cache: "no-store", signal: AbortSignal.timeout(4000) },
    );
    const value = await response.json().catch(() => ({}));
    return Response.json({ ...value, workspace: scope }, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Run details are temporarily unavailable" }, { status: 504 });
  }
}
