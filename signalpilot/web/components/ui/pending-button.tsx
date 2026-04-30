"use client";

/**
 * Unified spinner+disabled treatment for any async button.
 * Imports class constants from auth-primitives — does NOT redefine them.
 * Line budget: < 90 lines.
 */

import React from "react";
import { Loader2 } from "lucide-react";
import {
  PRIMARY_BTN_CLASS,
  SECONDARY_BTN_CLASS,
  DANGER_BTN_CLASS,
} from "@/components/auth/auth-primitives";

export type PendingButtonVariant = "default" | "danger" | "secondary";
export type PendingButtonSize = "sm" | "md";

export interface PendingButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  pending: boolean;
  pendingLabel?: string;
  variant?: PendingButtonVariant;
  size?: PendingButtonSize;
  children: React.ReactNode;
}

const SM_PRIMARY_CLASS =
  "flex items-center gap-1.5 px-3 py-1.5 bg-[var(--color-text)] text-[var(--color-bg)] text-[11px] uppercase tracking-wider hover:opacity-90 transition-opacity disabled:opacity-40 font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";

const SM_DANGER_CLASS =
  "flex items-center gap-1.5 px-3 py-1.5 bg-[var(--color-error)]/10 border border-[var(--color-error)]/40 text-[var(--color-error)] text-[11px] uppercase tracking-wider hover:bg-[var(--color-error)]/20 transition-colors disabled:opacity-40 font-mono focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)]";

function resolveClass(variant: PendingButtonVariant, size: PendingButtonSize): string {
  if (size === "sm") {
    if (variant === "danger") return SM_DANGER_CLASS;
    if (variant === "secondary") return SECONDARY_BTN_CLASS;
    return SM_PRIMARY_CLASS;
  }
  // md
  if (variant === "danger") return `flex items-center gap-2 ${DANGER_BTN_CLASS}`;
  if (variant === "secondary") return `flex items-center gap-2 ${SECONDARY_BTN_CLASS}`;
  return `flex items-center gap-2 ${PRIMARY_BTN_CLASS}`;
}

export function PendingButton({
  pending,
  pendingLabel,
  variant = "default",
  size = "md",
  children,
  disabled,
  className,
  ...rest
}: PendingButtonProps): React.JSX.Element {
  const baseClass = resolveClass(variant, size);
  const combined = className ? `${baseClass} ${className}` : baseClass;

  return (
    <button
      {...rest}
      disabled={pending || disabled}
      aria-busy={pending}
      className={combined}
    >
      {pending && (
        <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" aria-hidden="true" />
      )}
      {pending ? (pendingLabel ?? children) : children}
    </button>
  );
}
