import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const isAuthenticated = !!req.auth;
  const path = req.nextUrl.pathname;

  const protectedPaths = ["/setup", "/dashboard"];
  const isProtected = protectedPaths.some((p) => path.startsWith(p));

  if (isProtected && !isAuthenticated) {
    const signupUrl = new URL("/signup", req.nextUrl.origin);
    return NextResponse.redirect(signupUrl);
  }

  // Redirect /dashboard to /setup (no dashboard page yet)
  if (path.startsWith("/dashboard")) {
    const setupUrl = new URL("/setup", req.nextUrl.origin);
    return NextResponse.redirect(setupUrl);
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/setup/:path*", "/dashboard/:path*"],
};
