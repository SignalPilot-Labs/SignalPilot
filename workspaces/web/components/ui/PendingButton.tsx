"use client";

/**
 * Unified spinner+disabled treatment for async form submits.
 * Resolves button classes from workspaces' own button-classes module.
 */

import React from "react";
import { Loader2 } from "lucide-react";
import {
  PRIMARY_BTN_CLASS,
  SECONDARY_BTN_CLASS,
  DANGER_BTN_CLASS,
  SM_PRIMARY_CLASS,
  SM_DANGER_CLASS,
} from "@/components/ui/button-classes";

export type PendingButtonVariant = "primary" | "secondary" | "danger";
export type PendingButtonSize = "sm" | "md";

export interface PendingButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  pending: boolean;
  pendingLabel?: string;
  variant?: PendingButtonVariant;
  size?: PendingButtonSize;
  children: React.ReactNode;
}

function resolveClass(variant: PendingButtonVariant, size: PendingButtonSize): string {
  if (size === "sm") {
    if (variant === "danger") return `flex items-center gap-1.5 ${SM_DANGER_CLASS}`;
    if (variant === "secondary") return `flex items-center gap-1.5 ${SECONDARY_BTN_CLASS}`;
    return `flex items-center gap-1.5 ${SM_PRIMARY_CLASS}`;
  }
  // md
  if (variant === "danger") return `flex items-center gap-2 ${DANGER_BTN_CLASS}`;
  if (variant === "secondary") return `flex items-center gap-2 ${SECONDARY_BTN_CLASS}`;
  return `flex items-center gap-2 ${PRIMARY_BTN_CLASS}`;
}

export function PendingButton({
  pending,
  pendingLabel,
  variant = "primary",
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
