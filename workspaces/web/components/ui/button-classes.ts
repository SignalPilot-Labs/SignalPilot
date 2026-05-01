/**
 * Shared CSS class constants for buttons, inputs, labels, and errors.
 * Imported by Bucket B components and shared UI primitives.
 * No React dependency — pure constant module.
 */

export const FIELD_INPUT_CLASS =
  "px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[13px] text-[var(--color-text)] font-mono tracking-wide focus:outline-none focus:border-[var(--color-border-hover)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:border-[var(--color-text)] w-full";

export const PRIMARY_BTN_CLASS =
  "px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] uppercase tracking-wider hover:opacity-90 transition-opacity disabled:opacity-40 font-mono w-full focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";

export const SECONDARY_BTN_CLASS =
  "text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]";

export const DANGER_BTN_CLASS =
  "px-5 py-2.5 bg-[var(--color-error)]/10 border border-[var(--color-error)]/40 text-[var(--color-error)] text-[12px] uppercase tracking-wider hover:bg-[var(--color-error)]/20 transition-colors disabled:opacity-40 font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";

export const SM_PRIMARY_CLASS =
  "px-3 py-1.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[11px] uppercase tracking-wider hover:opacity-90 transition-opacity disabled:opacity-40 font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]";

export const SM_DANGER_CLASS =
  "px-3 py-1.5 bg-[var(--color-error)]/10 border border-[var(--color-error)]/40 text-[var(--color-error)] text-[11px] uppercase tracking-wider hover:bg-[var(--color-error)]/20 transition-colors disabled:opacity-40 font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]";

export const LABEL_CLASS =
  "text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-muted)]";

export const ERROR_CLASS =
  "text-[11px] text-[var(--color-error)] tracking-wider";
