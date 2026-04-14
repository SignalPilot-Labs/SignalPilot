"use client";

import { clsx } from "clsx";
import { forwardRef } from "react";

type Variant = "ghost" | "danger" | "success" | "warning" | "primary";
type Size = "sm" | "md" | "lg";

const variantStyles: Record<Variant, string> = {
  ghost:
    "bg-white/[0.04] text-[#aaa] hover:bg-white/[0.08] hover:text-white border-[#1a1a1a]",
  primary:
    "bg-[#88ccff]/10 text-[#88ccff] hover:bg-[#88ccff]/20 border-[#88ccff]/20",
  danger:
    "bg-[#ff4444]/8 text-[#ff4444] hover:bg-[#ff4444]/15 border-[#ff4444]/15",
  success:
    "bg-[#00ff88]/8 text-[#00ff88] hover:bg-[#00ff88]/15 border-[#00ff88]/15",
  warning:
    "bg-[#ffaa00]/8 text-[#ffaa00] hover:bg-[#ffaa00]/15 border-[#ffaa00]/15",
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { variant = "ghost", size = "sm", icon, children, className, ...props },
    ref,
  ) => (
    <button
      ref={ref}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded border font-medium transition-all duration-150",
        "disabled:opacity-30 disabled:pointer-events-none",
        "active:scale-[0.97]",
        variantStyles[variant],
        size === "sm" ? "px-2 py-1 text-[10px]" : size === "md" ? "px-3 py-1.5 text-[11px]" : "px-4 py-2.5 text-[13px] min-h-[44px]",
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  ),
);

Button.displayName = "Button";
