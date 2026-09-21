import { collectProjectBootstrap } from "../../../lib/project-bootstrap";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const result = await collectProjectBootstrap();
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to collect project evidence" }, { status: 500 });
  }
}
