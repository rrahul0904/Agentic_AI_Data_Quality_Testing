import { workspaceQuery, resolveWorkspace } from "../../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const source = new URL(request.url).searchParams;
    const params = new URLSearchParams(workspaceQuery(scope));
    if (source.get("check_connectivity") === "true") params.set("check_connectivity", "true");
    if (source.get("verify_model") === "true") params.set("verify_model", "true");
    const response = await fetch(`${API_BASE}/api/v1/demo/readiness?${params.toString()}`, {
      cache: "no-store",
      headers: {
        "x-ade-project-id": scope.projectId,
        "x-ade-environment": scope.environment,
      },
      signal: AbortSignal.timeout(15000),
    });
    const value = await response.json().catch(() => ({}));
    return Response.json(value, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load demo readiness" }, { status: 502 });
  }
}
