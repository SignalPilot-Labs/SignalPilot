"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTierUpgrade } from "@/lib/hooks/use-tier-upgrade";
import { TIER_BRANDS, type BrandTier, type TierBrand } from "@/lib/tier-branding";

// Per-tier dismiss delays — Enterprise copy is longest, gets the most time.
const DISMISS_DELAY_MS: Record<BrandTier, number> = {
  free: 8000,
  pro: 6000,
  team: 8000,
  enterprise: 12000,
};
const EXIT_DURATION_MS = 160;

const HEADLINE_ID = "tier-celebration-headline";

const BODY_COPY: Record<BrandTier, string> = {
  free: "",
  pro: "Higher rate limits (10k req/day) and additional API keys are now available.",
  team: "Shared pipelines and team membership are active. Up to 100k requests/day.",
  enterprise: "SSO, audit log export, and org-level access controls are active.",
};

/**
 * Self-contained, mount-point-agnostic tier upgrade celebration overlay.
 * Renders nothing when there is nothing to celebrate (returns null early).
 * No props — all state is owned by useTierUpgrade().
 */
export default function TierUpgradeCelebration() {
  const { celebratingTier, dismiss } = useTierUpgrade();
  const [exiting, setExiting] = useState(false);

  // Track hover/focus so we can pause the auto-dismiss timer.
  const pausedRef = useRef(false);
  // Ref to close button for focus management.
  const closeRef = useRef<HTMLButtonElement>(null);
  // Ref to the element that had focus before the overlay opened.
  const previousFocusRef = useRef<HTMLElement | null>(null);
  // Ref to the pending exit setTimeout so we can cancel it on unmount.
  const exitTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleDismiss = useCallback(() => {
    setExiting(true);
    exitTimeoutRef.current = setTimeout(dismiss, EXIT_DURATION_MS);
  }, [dismiss]);

  // Cleanup exit timeout on unmount to avoid calling setState on an
  // unmounted component.
  useEffect(() => {
    return () => {
      if (exitTimeoutRef.current !== null) {
        clearTimeout(exitTimeoutRef.current);
      }
    };
  }, []);

  // Auto-dismiss with pause-on-hover/focus support.
  useEffect(() => {
    if (!celebratingTier) return;

    const delay = DISMISS_DELAY_MS[celebratingTier];
    let remaining = delay;
    let start = Date.now();
    let timerId: ReturnType<typeof setTimeout> | null = null;

    function schedule() {
      timerId = setTimeout(() => {
        if (!pausedRef.current) {
          handleDismiss();
        }
      }, remaining);
    }

    function pause() {
      if (timerId !== null) {
        clearTimeout(timerId);
        timerId = null;
        remaining -= Date.now() - start;
      }
      pausedRef.current = true;
    }

    function resume() {
      pausedRef.current = false;
      start = Date.now();
      schedule();
    }

    schedule();

    const cardEl = document.getElementById("tier-celebration-card");
    if (cardEl) {
      cardEl.addEventListener("mouseenter", pause);
      cardEl.addEventListener("mouseleave", resume);
      cardEl.addEventListener("focusin", pause);
      cardEl.addEventListener("focusout", resume);
    }

    return () => {
      if (timerId !== null) clearTimeout(timerId);
      if (cardEl) {
        cardEl.removeEventListener("mouseenter", pause);
        cardEl.removeEventListener("mouseleave", resume);
        cardEl.removeEventListener("focusin", pause);
        cardEl.removeEventListener("focusout", resume);
      }
    };
  }, [celebratingTier, handleDismiss]);

  // Esc key dismisses.
  useEffect(() => {
    if (!celebratingTier) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") handleDismiss();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [celebratingTier, handleDismiss]);

  // Focus management: move focus to close button on open; restore on close.
  useEffect(() => {
    if (celebratingTier) {
      previousFocusRef.current = document.activeElement as HTMLElement | null;
      const t = setTimeout(() => closeRef.current?.focus(), 0);
      return () => clearTimeout(t);
    } else {
      if (previousFocusRef.current && "focus" in previousFocusRef.current) {
        previousFocusRef.current.focus();
      }
      previousFocusRef.current = null;
    }
  }, [celebratingTier]);

  if (!celebratingTier) return null;

  const brand = TIER_BRANDS[celebratingTier];
  const tierLabel = brand.label;

  return (
    // Backdrop — z-[80] sits below toasts (z-[90])
    <div
      className={`fixed inset-0 z-[80] flex items-center justify-center ${
        exiting ? "animate-fade-out" : "animate-fade-in"
      }`}
    >
      {/* Backdrop — clicking dismisses */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={handleDismiss}
        aria-hidden="true"
      />

      {/* Card */}
      <div
        id="tier-celebration-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={HEADLINE_ID}
        aria-label={`${tierLabel} upgrade celebration`}
        className={`relative z-10 w-full max-w-sm mx-4 bg-[var(--color-bg-card)] border border-[var(--color-border)] overflow-hidden ${
          exiting ? "animate-slide-out-up" : "animate-slide-in-up"
        }`}
      >
        {/* 1px top accent strip — the only tier signal on the card */}
        {brand.accentHex && (
          <div
            className="h-px w-full"
            style={{ backgroundColor: brand.accentHex }}
            aria-hidden="true"
          />
        )}

        {/* Close button — top-4 right-4 aligns with content p-4 */}
        <button
          ref={closeRef}
          type="button"
          onClick={handleDismiss}
          className="absolute top-4 right-4 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-current"
          aria-label="Dismiss"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
            <path
              d="M2 2L8 8M8 2L2 8"
              stroke="currentColor"
              strokeWidth="1"
              strokeLinecap="round"
            />
          </svg>
        </button>

        <div className="p-4">
          <CelebrationContent tier={celebratingTier} brand={brand} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CelebrationContent — shared across all paid tiers
// ---------------------------------------------------------------------------

interface CelebrationContentProps {
  tier: BrandTier;
  brand: TierBrand;
}

function CelebrationContent({ tier, brand }: CelebrationContentProps) {
  const headline = `${brand.label} is active.`;
  const bodyCopy = BODY_COPY[tier];

  return (
    <div className="space-y-3">
      {/* Tier label row */}
      <div className="flex items-center gap-1.5">
        {brand.accentHex && (
          <span
            className="inline-block w-[5px] h-[5px] flex-shrink-0"
            style={{ backgroundColor: brand.accentHex }}
            aria-hidden="true"
          />
        )}
        <span className="text-[10px] tracking-[0.2em] uppercase text-[var(--color-text-muted)]">
          {brand.label}
        </span>
      </div>

      {/* Headline */}
      <h2
        id={HEADLINE_ID}
        className="text-[15px] font-light text-[var(--color-text)] tracking-tight leading-snug"
      >
        {headline}
      </h2>

      {/* Body */}
      {bodyCopy && (
        <p className="text-[13px] text-[var(--color-text-muted)]">
          {bodyCopy}
        </p>
      )}
    </div>
  );
}
