/** Small defensive accessors for the untyped run-event payloads. */

export function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/** The proxy's sign-in error; the transcript shows a card for it instead. */
export const CONNECTOR_NEEDS_SIGN_IN = /needs you to sign in/i;

export function chatToolSummary(value: unknown): string | null {
  return text(value)?.replace(/\bgoverned tool\b/gi, "tool") ?? null;
}

export const durationBetween = (start: string, end: string): number | null => {
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  return Number.isFinite(startMs) && Number.isFinite(endMs)
    ? Math.max(0, endMs - startMs)
    : null;
};
