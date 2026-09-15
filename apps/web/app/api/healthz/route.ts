import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET(): NextResponse {
  return NextResponse.json({
    status: "PASS",
    service: "ade-web",
    backendConfigured: Boolean(process.env.ADE_API_URL?.trim()),
    timestamp: new Date().toISOString(),
  });
}
