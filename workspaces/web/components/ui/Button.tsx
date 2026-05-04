"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import {
  PRIMARY_BTN_CLASS,
  SECONDARY_BTN_CLASS,
  DANGER_BTN_CLASS,
  SM_PRIMARY_CLASS,
  SM_DANGER_CLASS,
} from "@/components/ui/button-classes";

export type ButtonVariant = "primary" | "secondary" | "danger";
export type ButtonSize = "sm" | "md";

interface ButtonProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  pending?: boolean;
  pendingLabel?: string;
  disabled?: boolean;
  type?: "button" | "submit" | "reset";
  onClick?: () => void;
  children: ReactNode;
  className?: string;
}

function resolveClass(variant: ButtonVariant, size: ButtonSize): string {
  if (size === "sm") {
    if (variant === "danger") return SM_DANGER_CLASS;
    if (variant === "secondary") return SECONDARY_BTN_CLASS;
    return SM_PRIMARY_CLASS;
  }
  if (variant === "danger") return DANGER_BTN_CLASS;
  if (variant === "secondary") return SECONDARY_BTN_CLASS;
  return PRIMARY_BTN_CLASS;
}

export function Button({
  variant = "primary",
  size = "md",
  pending = false,
  pendingLabel,
  disabled,
  type = "button",
  onClick,
  children,
  className = "",
}: ButtonProps) {
  const baseClass = resolveClass(variant, size);
  const isDisabled = disabled || pending;

  return (
    <button
      type={type}
      disabled={isDisabled}
      aria-busy={pending}
      onClick={onClick}
      className={`${baseClass} ${className}`}
    >
      {pending && pendingLabel ? pendingLabel : children}
    </button>
  );
}

interface LinkButtonProps {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
  className?: string;
}

export function LinkButton({
  href,
  variant = "primary",
  size = "md",
  children,
  className = "",
}: LinkButtonProps) {
  const baseClass = resolveClass(variant, size);
  return (
    <Link href={href} className={`${baseClass} inline-block text-center ${className}`}>
      {children}
    </Link>
  );
}
