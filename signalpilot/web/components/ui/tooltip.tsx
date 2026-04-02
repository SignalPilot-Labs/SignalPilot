"use client";

import { useState, useRef, useEffect } from "react";

/**
 * Terminal-aesthetic tooltip — appears above the trigger element.
 * Pure CSS positioning with a micro entrance animation.
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
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      onTouchStart={(e) => {
        // On mobile, toggle tooltip on tap
        e.stopPropagation();
        if (visible) {
          handleLeave();
        } else {
          clearTimeout(timeoutRef.current);
          setVisible(true);
          // Auto-hide after 2 seconds on touch
          timeoutRef.current = setTimeout(() => setVisible(false), 2000);
        }
      }}
    >
      {children}
      {visible && (
        <span
          className={`absolute z-50 ${positionClasses[position]} px-2 py-1 bg-[var(--color-bg-elevated)] border border-[var(--color-border)] text-[10px] text-[var(--color-text-muted)] whitespace-nowrap tracking-wider animate-fade-in pointer-events-none`}
        >
          {content}
        </span>
      )}
    </span>
  );
}
