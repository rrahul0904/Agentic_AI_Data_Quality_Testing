import { resolveWorkspace } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return Response.json(await resolveWorkspace(request), { headers: { "Cache-Control": "no-store" } });
}
