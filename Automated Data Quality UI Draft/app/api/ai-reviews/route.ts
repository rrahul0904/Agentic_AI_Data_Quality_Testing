import { resolveWorkspace, workspaceQuery } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

function headers(request: Request, projectId: string, init?: RequestInit) {
  const value = new Headers(init?.headers);
  value.set("content-type", "application/json");
  for (const name of ["x-ade-api-key", "x-ade-identity", "x-ade-project-id", "x-ade-environment"]) {
    const incoming = request.headers.get(name) ?? (name === "x-ade-api-key" ? process.env.ADE_UI_API_KEY : undefined);
    if (incoming) value.set(name, incoming);
  }
  value.set("x-ade-project-id", projectId);
  return value;
}

async function backend(endpoint: string, scope: Awaited<ReturnType<typeof resolveWorkspace>>, request: Request, init?: RequestInit) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...init,
    headers: headers(request, scope.projectId, init),
    cache: "no-store",
    signal: AbortSignal.timeout(120000),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `AI review request returned ${response.status}`);
  return body;
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const query = new URL(request.url).searchParams;
    const suffix = new URLSearchParams(workspaceQuery(scope));
    for (const name of ["selected_asset", "run_id", "limit"]) {
      const value = query.get(name);
      if (value) suffix.set(name, value);
    }
    return Response.json(await backend(`/api/v1/ai/reviews?${suffix.toString()}`, scope, request));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load AI reviews" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const body = await request.json() as Record<string, unknown>;
    return Response.json(await backend("/api/v1/ai/reviews", scope, request, {
      method: "POST",
      body: JSON.stringify({
        project_id: scope.projectId,
        environment: scope.environment,
        review_case: body.review_case,
        selected_asset: body.selected_asset ?? null,
        run_id: body.run_id ?? null,
      }),
    }));
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to invoke AI review" }, { status: 502 });
  }
}
