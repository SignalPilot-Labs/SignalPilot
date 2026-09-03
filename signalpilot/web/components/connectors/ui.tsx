"use client";

// Small shared pieces for the Connectors surfaces. Everything here is
// token-only, focus-visible, and sized for touch.

import { Loader2, MoreHorizontal } from "lucide-react";
import {
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import { Menu, useMenuTrigger, type MenuItem } from "~/components/ui/menu";

export type { MenuItem };

export const FOCUS_RING =
  "outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-card)]";

const BUTTON_BASE = `inline-flex min-h-[36px] items-center justify-center gap-1.5 whitespace-nowrap rounded-[var(--radius-ctl)] px-3.5 text-[12.5px] font-medium transition-[background-color,border-color,color,opacity] duration-150 disabled:cursor-not-allowed disabled:opacity-40 ${FOCUS_RING}`;

const VARIANTS = {
  primary: "bg-[var(--color-text)] text-[var(--color-bg)] hover:bg-[var(--color-accent-hover)]",
  secondary:
    "border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text)] hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)]",
  ghost: "text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]",
  danger:
    "border border-[var(--color-error)]/35 bg-[var(--color-error)]/10 text-[var(--color-error)] hover:bg-[var(--color-error)]/18",
} as const;

export function Button({
  variant = "secondary",
  pending = false,
  children,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof VARIANTS;
  pending?: boolean;
}) {
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || pending}
      aria-busy={pending || undefined}
      className={`${BUTTON_BASE} ${VARIANTS[variant]} ${className}`}
    >
      {pending && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function TextInput({
  className = "",
  mono = false,
  invalid = false,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { mono?: boolean; invalid?: boolean }) {
  return (
    <input
      {...rest}
      aria-invalid={invalid || undefined}
      className={`min-h-[40px] w-full rounded-[var(--radius-ctl)] border bg-[var(--color-bg-input)] px-3 text-[13px] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] placeholder:!opacity-100 transition-colors focus:!shadow-none focus:outline-none focus-visible:!outline-none disabled:cursor-not-allowed disabled:border-dashed disabled:bg-transparent disabled:text-[var(--color-text-muted)] disabled:opacity-60 ${
        invalid
          ? "border-[var(--color-error)]/60 focus:border-[var(--color-error)]"
          : "border-[var(--color-border)] hover:border-[var(--color-border-hover)] focus:border-[var(--color-border-active)]"
      } ${mono ? "font-mono text-[12.5px]" : ""} ${className}`}
    />
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[12px] font-medium text-[var(--color-text-muted)]">
        {label}
      </label>
      {children}
      {error ? (
        <p role="alert" className="text-[12px] leading-5 text-[var(--color-error)]">
          {error}
        </p>
      ) : hint ? (
        <p className="text-[12px] leading-5 text-[var(--color-text-dim)]">{hint}</p>
      ) : null}
    </div>
  );
}

/** Eyebrow label used for section titles inside cards, drawers, and panels. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p className={`text-[10.5px] font-medium uppercase tracking-[0.1em] text-[var(--color-text-dim)] ${className}`}>
      {children}
    </p>
  );
}

const CHIP_TONES = {
  neutral: "border-[var(--color-border)] text-[var(--color-text-muted)]",
  read: "border-[var(--color-success)]/25 bg-[var(--color-success)]/[0.06] text-[var(--color-success)]",
  write: "border-[var(--color-warning)]/30 bg-[var(--color-warning)]/[0.06] text-[var(--color-warning)]",
  destructive: "border-[var(--color-error)]/35 bg-[var(--color-error)]/[0.07] text-[var(--color-error)]",
  fresh: "border-[var(--color-text)]/20 bg-[var(--color-text)]/[0.06] text-[var(--color-text)]",
} as const;

export function Chip({
  tone = "neutral",
  children,
  className = "",
  testId,
}: {
  tone?: keyof typeof CHIP_TONES;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className={`inline-flex h-[18px] flex-none items-center rounded-full border px-1.5 text-[10px] font-medium leading-none tracking-[0.02em] ${CHIP_TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/** Notice line for warnings and honest labels (the sandbox caveat, etc.). */
export function Notice({
  tone = "info",
  icon,
  children,
  className = "",
  testId,
}: {
  tone?: "info" | "warning" | "error" | "success";
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  const tones = {
    info: "border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)]",
    warning: "border-[var(--color-warning)]/25 bg-[var(--color-warning)]/[0.06] text-[var(--color-warning)]",
    error: "border-[var(--color-error)]/25 bg-[var(--color-error)]/[0.06] text-[var(--color-error)]",
    success: "border-[var(--color-success)]/25 bg-[var(--color-success)]/[0.05] text-[var(--color-text)]",
  };
  return (
    <div
      data-testid={testId}
      className={`flex items-start gap-2.5 rounded-[var(--radius-ctl)] border px-3 py-2.5 text-[12.5px] leading-5 ${tones[tone]} ${className}`}
    >
      {icon && <span className="mt-0.5 flex-none">{icon}</span>}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/**
 * Kebab menu: 44px hit area; the popup is a body-level portal (see
 * `components/ui/menu.tsx`) so it is never trapped under the next row or
 * clipped by the list container. Arrow keys, Home/End, Escape (returns
 * focus), Tab and blur close it.
 */
export function KebabMenu({
  items,
  label,
  testId,
}: {
  items: MenuItem[];
  label: string;
  testId?: string;
}) {
  const { anchorRef, open, setOpen, close } = useMenuTrigger();
  const menuId = useId();
  return (
    <div className="relative z-10 flex-none" onClick={(e) => e.stopPropagation()}>
      <button
        ref={anchorRef}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        data-testid={testId}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
          }
        }}
        className={`flex h-11 w-11 items-center justify-center rounded-[var(--radius-ctl)] text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] sm:h-9 sm:w-9 ${FOCUS_RING}`}
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
      </button>
      <Menu open={open} onClose={close} anchorRef={anchorRef} items={items} label={label} />
    </div>
  );
}

/** Relative time, coarse ("just now", "4m ago", "Yesterday", "Jun 3"). */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  if (seconds < 172_800) return "yesterday";
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
