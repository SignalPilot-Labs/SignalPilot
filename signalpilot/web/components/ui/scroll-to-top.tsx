"use client";

import { useEffect, useState } from "react";

/**
 * Floating "back to top" button that appears after scrolling down.
 * Only visible on mobile — desktop users can use keyboard shortcuts.
 * Positioned above the bottom tab bar.
 */
export function ScrollToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    function handleScroll() {
      setVisible(window.scrollY > 600);
    }
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  if (!visible) return null;

  return (
    <button
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      className="sm:hidden fixed left-4 bottom-[calc(3.5rem+env(safe-area-inset-bottom,0px)+0.75rem)] z-40 flex items-center justify-center w-10 h-10 bg-[var(--color-bg-card)]/90 backdrop-blur-sm border border-[var(--color-border)] text-[var(--color-text-dim)] active:bg-[var(--color-bg-hover)] active:text-[var(--color-text)] transition-all animate-fade-in"
      aria-label="Scroll to top"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path
          d="M7 11V3M3 6L7 2L11 6"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
