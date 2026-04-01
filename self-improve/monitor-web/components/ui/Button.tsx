"use client";

import { clsx } from "clsx";
import { forwardRef } from "react";

type Variant = "ghost" | "danger" | "success" | "warning" | "primary";

const variantStyles: Record<Variant, string> = {
  ghost:
    "bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white border-white/5",
  primary:
    "bg-sky-500/15 text-sky-400 hover:bg-sky-500/25 border-sky-500/20",
  danger:
    "bg-red-500/10 text-red-400 hover:bg-red-500/20 border-red-500/20",
  success:
    "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border-emerald-500/20",
  warning:
    "bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 border-amber-500/20",
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  icon?: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "ghost", size = "sm", icon, children, className, ...props }, ref) => (
    <button
      ref={ref}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-lg border font-medium transition-all duration-150",
        "disabled:opacity-30 disabled:pointer-events-none",
        "active:scale-[0.97]",
        variantStyles[variant],
        size === "sm" ? "px-2.5 py-1 text-[11px]" : "px-3.5 py-1.5 text-xs",
        className
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  )
);

Button.displayName = "Button";
