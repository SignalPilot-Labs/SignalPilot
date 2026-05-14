"use client";

import { useState, useRef, useEffect, useId } from "react";

/**
 * Terminal-aesthetic tooltip.
 * Pure CSS positioning with a micro entrance animation.
 *
 * Accessibility: the outer wrapper is focusable (tabIndex={0}) so keyboard users
 * can reach tooltips wrapping non-interactive content.
 */
export function Tooltip({
  content,
  children,
  position = "top",
  delay = 200,
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  position?: "top" | "bottom" | "left" | "right";
  delay?: number;
}) {
  const [visible, setVisible] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const tooltipId = useId();

  function handleEnter() {
    timeoutRef.current = setTimeout(() => setVisible(true), delay);
  }

  function handleLeave() {
    clearTimeout(timeoutRef.current);
    setVisible(false);
  }

  useEffect(() => {
    return () => clearTimeout(timeoutRef.current);
  }, []);

  const positionClasses: Record<string, string> = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-1.5",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-1.5",
    left: "right-full top-1/2 -translate-y-1/2 mr-1.5",
    right: "left-full top-1/2 -translate-y-1/2 ml-1.5",
  };

  return (
    <span
      className="relative inline-flex"
      tabIndex={0}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      onFocus={handleEnter}
      onBlur={handleLeave}
      aria-describedby={visible ? tooltipId : undefined}
    >
      {children}
      {visible && (
        <span
          id={tooltipId}
          role="tooltip"
          className={`absolute z-50 ${positionClasses[position]} px-2 py-1 bg-[var(--color-bg-elevated)] border border-[var(--color-border)] text-[12px] text-[var(--color-text-muted)] whitespace-nowrap tracking-wider animate-fade-in pointer-events-none`}
        >
          {content}
        </span>
      )}
    </span>
  );
}
