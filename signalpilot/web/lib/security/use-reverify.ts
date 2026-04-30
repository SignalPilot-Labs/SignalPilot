/**
 * Narrow responsibility: centralizes reverification-cancelled detection so
 * every section handles it identically.
 * Does NOT wrap useReverification — call sites import it directly from
 * @clerk/nextjs so options and return types are preserved.
 */

// Re-exported for one-import-site ergonomics.
// useReverification comes from the main @clerk/nextjs barrel.
export { useReverification } from "@clerk/nextjs";

// isReverificationCancelledError is exported from @clerk/nextjs/errors.
export { isReverificationCancelledError } from "@clerk/nextjs/errors";
