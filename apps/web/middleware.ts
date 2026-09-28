import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  if (request.nextUrl.pathname === "/") {
    return NextResponse.redirect(new URL("/investigations", request.url));
  }
  return NextResponse.next();
}

export const config = { matcher: ["/"] };
