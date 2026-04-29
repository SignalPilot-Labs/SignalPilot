"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Crown } from "lucide-react";
import { useTierUpgrade } from "@/lib/hooks/use-tier-upgrade";
import { TIER_BRANDS, type BrandTier } from "@/lib/tier-branding";
import { TierBadge } from "@/components/branding/tier-badge";
import { TierWordmark } from "@/components/branding/tier-wordmark";
import { TierAccent } from "@/components/branding/tier-accent";
import { TierSeal } from "@/components/branding/tier-seal";

// Per-tier dismiss delays — Enterprise copy is longest, gets the most time.
const DISMISS_DELAY_MS: Record<BrandTier, number> = {
  free: 8000,
  pro: 6000,
  team: 8000,
  enterprise: 12000,
};
const EXIT_DURATION_MS = 160;

const HEADLINE_ID = "tier-celebration-headline";

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
      // Record where focus was before the overlay opened.
      previousFocusRef.current = document.activeElement as HTMLElement | null;
      // Small delay to let the component fully render before attempting focus.
      const t = setTimeout(() => closeRef.current?.focus(), 0);
      return () => clearTimeout(t);
    } else {
      // Overlay closed — restore previous focus.
      if (previousFocusRef.current && "focus" in previousFocusRef.current) {
        previousFocusRef.current.focus();
      }
      previousFocusRef.current = null;
    }
  }, [celebratingTier]);

  if (!celebratingTier) return null;

  const tierLabel = TIER_BRANDS[celebratingTier].label;

  return (
    // Backdrop — z-[80] sits below toasts (z-[90])
    <div
      className={`fixed inset-0 z-[80] flex items-center justify-center ${
        exiting ? "animate-fade-out" : "animate-fade-in"
      }`}
    >
      {/* Backdrop — clicking dismisses */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
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
        className={`relative z-10 w-full max-w-sm mx-4 bg-[var(--color-bg-card)] border ${
          celebratingTier === "pro"
            ? "border-indigo-500/40 bg-indigo-500/10"
            : celebratingTier === "team"
            ? "border-violet-400/50"
            : "border-amber-400/50"
        } ${
          celebratingTier === "team"
            ? "bg-violet-500/10"
            : celebratingTier === "enterprise"
            ? "bg-gradient-to-b from-amber-500/10 to-transparent"
            : ""
        } shadow-xl ${exiting ? "animate-slide-out-up" : "animate-slide-in-up"}`}
      >
        {/* Close button */}
        <button
          ref={closeRef}
          type="button"
          onClick={handleDismiss}
          className="absolute top-3 right-3 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-current"
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

        <div className="p-5">
          {celebratingTier === "pro" && <ProVariant />}
          {celebratingTier === "team" && <TeamVariant />}
          {celebratingTier === "enterprise" && <EnterpriseVariant />}
        </div>
      </div>
    </div>
  );
}

// ── Pro variant — clear step up: indigo wash, prominent headline ──────────────

function ProVariant() {
  return (
    <div className="space-y-3">
      <h2
        id={HEADLINE_ID}
        className="text-[15px] font-semibold text-[var(--color-text)] tracking-tight leading-snug"
      >
        Welcome to Pro
      </h2>
      <div className="flex items-center gap-2">
        <TierBadge size="md" />
        <span className="text-[12px] text-indigo-400/70 tracking-wide">
          Your Pro badge is active
        </span>
      </div>
      <p className="text-[13px] text-[var(--color-text-muted)]">
        Your new badge is live across the app.
      </p>
      <TierAccent />
    </div>
  );
}

// ── Team variant — richer ─────────────────────────────────────────────────────

function TeamVariant() {
  return (
    <div className="space-y-3">
      <TierAccent />
      <h2
        id={HEADLINE_ID}
        className="sr-only"
      >
        Welcome to Team
      </h2>
      <div className="flex items-center gap-2 py-1">
        <TierWordmark variant="header" />
      </div>
      <p className="text-[13px] text-[var(--color-text-muted)]">
        Invite your team and share signals together. Collaborators and shared
        pipelines are now live.
      </p>
      <TierAccent />
    </div>
  );
}

// ── Enterprise variant — most premium ────────────────────────────────────────
// TierCrest is a corner-overlay primitive; we feature the crown crest by
// rendering TierBadge (Crown icon + label) as the focal hero, centered, with
// TierSeal below as the authoritative wordmark. No placeholder squares.

function EnterpriseVariant() {
  return (
    <div className="space-y-4">
      <div className="flex flex-col items-center gap-3 pt-2 pb-1">
        <Crown
          size={40}
          strokeWidth={1.25}
          className="text-amber-300 drop-shadow-[0_0_12px_rgba(251,191,36,0.35)]"
          aria-hidden="true"
        />
        <TierSeal variant="header" />
      </div>
      <h2
        id={HEADLINE_ID}
        className="text-[15px] font-semibold text-[var(--color-text)] tracking-tight text-center leading-snug"
      >
        Enterprise is active
      </h2>
      <p className="text-[13px] text-[var(--color-text-muted)] text-center">
        The Enterprise edition is active. Your console now bears the crown.
      </p>
      <TierAccent />
    </div>
  );
}
