import { NextRequest, NextResponse } from "next/server";

type WebUser = { password: string; api_token: string };

function users(): Record<string, WebUser> {
  const raw = process.env.ADE_WEB_USERS_JSON?.trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as Record<string, WebUser>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function constantTimeEqual(left: string, right: string): boolean {
  const length = Math.max(left.length, right.length);
  let difference = left.length ^ right.length;
  for (let index = 0; index < length; index += 1) {
    difference |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
  }
  return difference === 0;
}

function authorized(request: NextRequest): boolean {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.toLowerCase().startsWith("basic ")) return false;
  try {
    const decoded = atob(authorization.slice(6));
    const separator = decoded.indexOf(":");
    if (separator < 0) return false;
    const username = decoded.slice(0, separator);
    const password = decoded.slice(separator + 1);
    const user = users()[username];
    return Boolean(user && constantTimeEqual(user.password, password));
  } catch {
    return false;
  }
}

export function middleware(request: NextRequest): NextResponse {
  if (request.nextUrl.pathname === "/api/healthz") {
    return NextResponse.next();
  }

  const mode = process.env.ADE_WEB_AUTH_MODE?.trim().toLowerCase() || "disabled";
  if (mode === "disabled") return NextResponse.next();

  if (mode !== "basic") {
    return NextResponse.json(
      { status: "AUTH_CONFIGURATION_REQUIRED", detail: "unsupported ADE_WEB_AUTH_MODE" },
      { status: 503 },
    );
  }

  if (!Object.keys(users()).length) {
    return NextResponse.json(
      { status: "AUTH_CONFIGURATION_REQUIRED", detail: "ADE_WEB_USERS_JSON is required" },
      { status: 503 },
    );
  }

  if (!authorized(request)) {
    return new NextResponse("Authentication required", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="ADE OS"' },
    });
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
