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

type WebUser = { password: string; api_token: string };

function webUsers(): Record<string, WebUser> {
  const raw = process.env.ADE_WEB_USERS_JSON?.trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as Record<string, WebUser>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function apiTokenForRequest(request: NextRequest): string | null {
  const serviceToken = process.env.ADE_API_SERVICE_TOKEN?.trim();
  const authorization = request.headers.get("authorization") || "";
  if (authorization.toLowerCase().startsWith("basic ")) {
    try {
      const decoded = atob(authorization.slice(6));
      const separator = decoded.indexOf(":");
      const username = separator >= 0 ? decoded.slice(0, separator) : "";
      const password = separator >= 0 ? decoded.slice(separator + 1) : "";
      const user = webUsers()[username];
      if (user && user.password === password && user.api_token) {
        return user.api_token;
      }
    } catch {
      return null;
    }
  }
  return serviceToken || null;
}

function upstreamHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (
      !HOP_BY_HOP.has(lower)
      && lower !== "content-length"
      && lower !== "authorization"
    ) {
      headers.set(key, value);
    }
  });
  const apiToken = apiTokenForRequest(request);
  if (apiToken) headers.set("authorization", `Bearer ${apiToken}`);
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
