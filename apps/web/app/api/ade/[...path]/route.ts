import { NextRequest, NextResponse } from "next/server";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
]);

function backendBase(): string | null {
  const configured = process.env.ADE_API_URL?.trim();
  if (configured) return configured.replace(/\/$/, "");
  if (process.env.NODE_ENV !== "production") return "http://127.0.0.1:8001";
  return null;
}

function upstreamHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "content-length") {
      headers.set(key, value);
    }
  });
  headers.set("accept", request.headers.get("accept") || "application/json");
  headers.set("x-ade-web-proxy", "1");
  return headers;
}

function downstreamHeaders(upstream: Response): Headers {
  const headers = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "content-length") {
      headers.set(key, value);
    }
  });
  headers.set("cache-control", "no-store");
  return headers;
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const base = backendBase();
  if (!base) {
    return NextResponse.json(
      {
        status: "BLOCKED_EXTERNAL",
        error: "ADE_API_URL is not configured for this deployed web service",
      },
      { status: 503 },
    );
  }

  const { path } = await context.params;
  const pathname = path.map(encodeURIComponent).join("/");
  const url = `${base}/${pathname}${request.nextUrl.search}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);

  try {
    const method = request.method.toUpperCase();
    const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
    const upstream = await fetch(url, {
      method,
      headers: upstreamHeaders(request),
      body,
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal,
    });
    const payload = await upstream.arrayBuffer();
    return new NextResponse(payload, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: downstreamHeaders(upstream),
    });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "AbortError";
    return NextResponse.json(
      {
        status: "FAIL",
        error: timedOut ? "ADE API request timed out" : "ADE API is unavailable",
      },
      { status: timedOut ? 504 : 502 },
    );
  } finally {
    clearTimeout(timer);
  }
}

export const dynamic = "force-dynamic";

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
