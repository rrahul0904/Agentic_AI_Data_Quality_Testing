import { resolveWorkspace } from "../../../lib/server-workspace";
import { isPhase4Fixture } from "../../../lib/server-test-fixture";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  if (isPhase4Fixture(request)) return Response.json({ projectId: "fixture-project", environment: "fixture" }, { headers: { "Cache-Control": "no-store", "X-ADQ-Test-Fixture": "phase4" } });
  return Response.json(await resolveWorkspace(request), { headers: { "Cache-Control": "no-store" } });
}
