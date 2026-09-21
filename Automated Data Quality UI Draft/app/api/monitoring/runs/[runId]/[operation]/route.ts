import { resolveWorkspace, workspaceQuery } from "../../../../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";
const allowedOperations = new Set(["reconcile", "resume", "verify"]);

export async function POST(request: Request, { params }: { params: Promise<{ runId: string; operation: string }> }) {
  const scope = await resolveWorkspace(request);
  const { runId, operation } = await params;
  if (!allowedOperations.has(operation)) return Response.json({ error: "Unsupported recovery operation" }, { status: 400 });
  const headers = new Headers({ "x-ade-project-id": scope.projectId, "content-type": "application/json" });
  const apiKey = request.headers.get("x-ade-api-key") ?? process.env.ADE_UI_API_KEY;
  if (apiKey) headers.set("x-ade-api-key", apiKey);
  const response = await fetch(`${API_BASE}/api/v1/actions/runs/${encodeURIComponent(runId)}/${operation}?${workspaceQuery(scope)}`, {
    method: "POST",
    headers,
    body: "{}",
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  const value = await response.json().catch(() => ({}));
  return Response.json(value, { status: response.status, headers: { "Cache-Control": "no-store" } });
}
