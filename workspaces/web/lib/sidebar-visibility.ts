/**
 * Routes where the sidebar and its offset are hidden.
 * Shared by Sidebar and MainContent so they always agree.
 */
export const HIDDEN_SIDEBAR_PREFIXES = ["/sign-in"];

export function shouldHideSidebar(pathname: string): boolean {
  return HIDDEN_SIDEBAR_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}
