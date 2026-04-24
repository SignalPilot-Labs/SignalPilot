/**
 * Shared CSS class constants and simple UI primitives for auth/team/security pages.
 * No @clerk/elements dependency — just plain class strings and basic React components.
 */

// ---------------------------------------------------------------------------
// CSS class constants — used across auth, team, and security sections
// ---------------------------------------------------------------------------

export const FIELD_INPUT_CLASS =
  "px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[13px] text-[var(--color-text)] font-mono tracking-wide focus:outline-none focus:border-[var(--color-border-hover)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:border-[var(--color-text)] w-full";

export const PRIMARY_BTN_CLASS =
  "px-5 py-2.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] uppercase tracking-wider hover:opacity-90 transition-opacity disabled:opacity-40 font-mono w-full focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";

export const LABEL_CLASS =
  "text-[11px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]";

export const ERROR_CLASS =
  "text-[11px] text-[var(--color-error)] tracking-wider";

export const NEUTRAL_CLASS =
  "text-[11px] text-[var(--color-text-dim)] tracking-wider";

export const SECONDARY_BTN_CLASS =
  "text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] tracking-wider underline underline-offset-2 transition-colors font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]";

export const DANGER_BTN_CLASS =
  "px-5 py-2.5 bg-[var(--color-error)]/10 border border-[var(--color-error)]/40 text-[var(--color-error)] text-[12px] uppercase tracking-wider hover:bg-[var(--color-error)]/20 transition-colors disabled:opacity-40 font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";

// ---------------------------------------------------------------------------
// Divider
// ---------------------------------------------------------------------------

export function Divider({ label = "or" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 my-1">
      <div className="flex-1 h-px bg-[var(--color-border)]" />
      <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider font-mono whitespace-nowrap">
        {label}
      </span>
      <div className="flex-1 h-px bg-[var(--color-border)]" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Footer link
// ---------------------------------------------------------------------------

export function FooterLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      className="text-[12px] text-[var(--color-text-dim)] tracking-wider hover:text-[var(--color-text)] transition-colors text-center block"
    >
      {children}
    </a>
  );
}
