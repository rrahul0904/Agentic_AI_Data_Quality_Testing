import type { NextRequest } from "next/server";

const BACKEND = process.env.ADE_API_URL ?? "http://127.0.0.1:8001";

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const target = new URL(path.map(encodeURIComponent).join("/"), `${BACKEND}/`);
  target.search = request.nextUrl.search;

  const response = await fetch(target, {
    method: request.method,
    headers: request.headers.get("content-type")
      ? { "content-type": request.headers.get("content-type") as string }
      : undefined,
    body: request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer(),
    cache: "no-store",
  });

  return new Response(response.body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
