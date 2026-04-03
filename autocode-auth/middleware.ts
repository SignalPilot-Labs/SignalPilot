import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const isAuthenticated = !!req.auth;
  const path = req.nextUrl.pathname;

  const protectedPaths = ["/setup"];
  const isProtected = protectedPaths.some((p) => path.startsWith(p));

  if (isProtected && !isAuthenticated) {
    const signupUrl = new URL("/signup", req.nextUrl.origin);
    return NextResponse.redirect(signupUrl);
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/setup/:path*"],
};
