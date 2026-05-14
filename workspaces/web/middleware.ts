import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { clerkMiddleware } from "@clerk/nextjs/server";

const cloud = clerkMiddleware();
const local = (_req: NextRequest) => NextResponse.next();

export default process.env["WORKSPACES_MODE"] === "cloud" ? cloud : local;

export const config = {
  matcher: [
    "/((?!_next|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|webp|ico|css|js|map)$).*)",
  ],
};
