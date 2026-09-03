"use client";

import { forwardRef, type KeyboardEvent } from "react";

/**
 * The one toggle primitive. A real `role="switch"` button: Space/Enter
 * toggle, focus-visible ring, honest disabled state, and a thumb that slides
 * (or snaps, under prefers-reduced-motion — the global rule zeroes the
 * transition). `sm` is for dense rows; both sizes meet the 44px touch
 * target through their padding box (the visual track stays 18px / 22px).
 */
export type SwitchProps = {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  size?: "sm" | "md";
  disabled?: boolean;
  /** Pending write: keeps the visual state, blocks a second click. */
  busy?: boolean;
  /** Accessible name. Prefer a visible <label> via aria-labelledby. */
  "aria-label"?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
  id?: string;
  className?: string;
  "data-testid"?: string;
};

const SIZES = {
  sm: { track: "h-[18px] w-[30px]", thumb: "h-[14px] w-[14px]", travel: 12, pad: "p-[2px]" },
  md: { track: "h-[22px] w-[38px]", thumb: "h-[18px] w-[18px]", travel: 16, pad: "p-[2px]" },
} as const;

export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  {
    checked,
    onCheckedChange,
    size = "md",
    disabled = false,
    busy = false,
    className = "",
    ...aria
  },
  ref,
) {
  const s = SIZES[size];
  const inert = disabled || busy;
  const toggle = () => {
    if (!inert) onCheckedChange(!checked);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    // Buttons fire click on Space/Enter natively; ArrowLeft/Right are the
    // WAI-ARIA switch conveniences.
    if (event.key === "ArrowRight" && !checked) {
      event.preventDefault();
      if (!inert) onCheckedChange(true);
    } else if (event.key === "ArrowLeft" && checked) {
      event.preventDefault();
      if (!inert) onCheckedChange(false);
    }
  };
  return (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-disabled={inert || undefined}
      aria-busy={busy || undefined}
      disabled={disabled}
      onClick={toggle}
      onKeyDown={onKeyDown}
      {...aria}
      className={`group/switch inline-flex flex-none touch-manipulation items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-card)] ${
        size === "md" ? "-m-[11px] p-[11px]" : "-m-[13px] p-[13px]"
      } ${disabled ? "cursor-not-allowed" : busy ? "cursor-progress" : "cursor-pointer"} ${className}`}
    >
      <span
        aria-hidden="true"
        className={`relative flex items-center rounded-full border transition-[background-color,border-color] duration-200 ease-out ${s.track} ${s.pad} ${
          checked
            ? "border-[var(--color-success)]/60 bg-[var(--color-success)]/85"
            : "border-[var(--color-border-hover)] bg-[var(--color-bg-input)]"
        } ${disabled ? "opacity-40" : ""}`}
      >
        <span
          className={`block rounded-full shadow-[0_1px_2px_rgba(0,0,0,0.45)] transition-transform duration-200 ease-out ${s.thumb} ${
            checked ? "bg-[#0b0b0c]" : "bg-[var(--color-text-muted)]"
          }`}
          style={{ transform: `translateX(${checked ? s.travel : 0}px)` }}
        />
      </span>
    </button>
  );
});
