// Which routes render without the app chrome (sidebar + offset main). One
// list, consumed by the sidebar and the main content wrapper so the two
// never disagree.

/** Auth, onboarding, and the notebook kiosk. */
export const CHROMELESS_ROUTE_PREFIXES = [
  "/sign-in",
  "/sign-up",
  "/onboarding",
  "/notebook",
] as const;

/** Exact-or-child match: "/dashboard" does not match "/dashboards". */
export function matchesRoutePrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function isChromelessRoute(pathname: string): boolean {
  return CHROMELESS_ROUTE_PREFIXES.some((prefix) => matchesRoutePrefix(pathname, prefix));
}
