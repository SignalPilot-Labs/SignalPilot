export const SPA_NAVIGATE_EVENT = "spa:navigate" as const;

declare global {
  interface WindowEventMap {
    [SPA_NAVIGATE_EVENT]: CustomEvent<{ href: string }>;
  }
}

/**
 * Standalone SPA navigation primitive. Pushes a new history entry and
 * notifies subscribers. Never reloads the document. Never falls back to
 * window.location.href — that hides bugs and breaks the in-page contract.
 */
export function spaNavigate(href: string): void {
  if (!href) throw new Error("spaNavigate: empty href");
  window.history.pushState({}, "", href);
  window.dispatchEvent(
    new CustomEvent(SPA_NAVIGATE_EVENT, { detail: { href } }),
  );
}
