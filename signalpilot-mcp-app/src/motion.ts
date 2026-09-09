/** True when the viewer asked for reduced motion (false where matchMedia is missing). */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Read a CSS custom property from an element's computed style. */
export function cssVar(element: Element, name: string, fallback = ""): string {
  const value = getComputedStyle(element).getPropertyValue(name).trim();
  return value || fallback;
}

export const TAU = Math.PI * 2;

/** mm:ss for the footer timer. */
export function formatClock(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
