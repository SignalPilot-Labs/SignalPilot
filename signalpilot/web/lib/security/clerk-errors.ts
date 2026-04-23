/**
 * Progressive error extraction from Clerk error shapes.
 * Not a layered fallback — we pick the best human-readable field
 * from a known Clerk error shape. The last branch is a diagnostic
 * escape hatch, not a silent default.
 */

interface ClerkErrorLike {
  errors?: Array<{
    longMessage?: string;
    message?: string;
    code?: string;
  }>;
}

export function formatClerkError(err: unknown): string {
  const e = err as ClerkErrorLike;
  if (e?.errors?.[0]?.longMessage) {
    return e.errors[0].longMessage;
  }
  if (e?.errors?.[0]?.message) {
    return e.errors[0].message;
  }
  if (err instanceof Error) {
    return err.message;
  }
  console.error("unrecognized error shape", err);
  return "unexpected error";
}
