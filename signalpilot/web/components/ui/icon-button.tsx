"use client";

import type { ButtonHTMLAttributes } from "react";
import type { LucideIcon } from "lucide-react";

export interface IconButtonProps
  extends Pick<ButtonHTMLAttributes<HTMLButtonElement>, "onClick" | "disabled" | "type"> {
  icon: LucideIcon;
  label: string;
  variant?: "ghost" | "destructive";
  size?: "sm";
}

const BASE =
  "p-1.5 transition-colors focus:outline-none focus-visible:outline-none " +
  "focus-visible:ring-1 focus-visible:ring-[var(--color-text)] " +
  "focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-card)] " +
  "disabled:opacity-50 disabled:cursor-not-allowed";

const VARIANT: Record<NonNullable<IconButtonProps["variant"]>, string> = {
  ghost:
    "text-[var(--color-text-dim)] hover:text-[var(--color-text)]",
  destructive:
    "text-[var(--color-text-dim)] hover:text-[var(--color-error)]",
};

export function IconButton({
  icon: Icon,
  label,
  onClick,
  disabled,
  type = "button",
  variant = "ghost",
  size: _size = "sm",
}: IconButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={`${BASE} ${VARIANT[variant]}`}
    >
      <Icon className="w-3.5 h-3.5" strokeWidth={1.5} aria-hidden="true" />
    </button>
  );
}
