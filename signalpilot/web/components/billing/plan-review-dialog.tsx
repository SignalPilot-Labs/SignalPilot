"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import type { PlanInfo, RateCard } from "~/lib/backend-client";
import { DEFAULT_RATE_CARD, creditRatesFrom, creditsToUsd, formatCredits, formatUsd } from "~/lib/billing-rates";
import {
  dueToday,
  feeLine,
  formatPrice,
  includedLine,
  monthlyPrice,
  primaryButtonLabel,
  seatEstimate,
  seatLines,
  type ProrationPreview,
  type ReviewMode,
} from "~/lib/billing-plan-review";
import { useFocusTrap } from "~/components/ui/use-focus-trap";

export type { ProrationPreview } from "~/lib/billing-plan-review";

export interface PlanReview {
  plan: PlanInfo;
  mode: ReviewMode;
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="py-3 border-b border-[var(--color-border)] last:border-b-0">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[10px] font-mono tabular-nums text-[var(--color-text-dim)]">{n}</span>
        <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">{title}</span>
      </div>
      {children}
    </div>
  );
}

function RateExpander({ rates, enterprise }: { rates: RateCard; enterprise: boolean }) {
  const [open, setOpen] = useState(false);
  const rows = creditRatesFrom(rates);
  return (
    <div>
      <button
        type="button"
        data-testid="review-rates-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-text)] underline-offset-2 hover:underline"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {open ? "hide rates" : "see the rate table"}
      </button>
      {open && (
        <ul data-testid="review-rates" className="mt-2 space-y-1">
          {rows.map((r) => {
            const credits = enterprise && r.enterpriseCredits !== undefined ? r.enterpriseCredits : r.credits;
            return (
              <li key={r.unit} className="flex items-baseline justify-between gap-3 text-[11px]">
                <span className="text-[var(--color-text-dim)]">
                  {r.label} <span className="opacity-70">/ {r.per}</span>
                </span>
                <span className="font-mono tabular-nums text-[var(--color-text-muted)] whitespace-nowrap">
                  {credits === null
                    ? `cost × ${rates.token_credits_per_dollar}`
                    : `${formatCredits(credits)} (${formatUsd(creditsToUsd(credits, rates))})`}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------

/**
 * "Review your plan": everything the customer will pay, in order, before any
 * checkout or plan change. The monthly fee, seats, included allowances,
 * credit rates, due today, then one primary action. Billing is monthly only;
 * the plan's `month` price is the one that is bought.
 */
export function PlanReviewDialog({
  review,
  members,
  rates,
  currentPeriodEnd,
  previewProration,
  onConfirm,
  onCancel,
  busy = false,
}: {
  review: PlanReview | null;
  /** Clerk member count; null when unknown. */
  members: number | null;
  rates: RateCard | null;
  currentPeriodEnd: string | null;
  /** Paid-to-paid changes fetch the Stripe proration for the monthly price. */
  previewProration?: (priceId: string) => Promise<ProrationPreview>;
  onConfirm: (priceId: string) => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);
  const open = review !== null;
  useFocusTrap(panelRef, open);

  const [previews, setPreviews] = useState<Record<string, ProrationPreview | null>>({});
  const [loadingPreview, setLoadingPreview] = useState(false);

  // A fresh review starts with no cached preview.
  const planKey = review ? `${review.plan.tier}:${review.mode}` : null;
  useEffect(() => {
    setPreviews({});
  }, [planKey]);

  useEffect(() => {
    if (open) primaryRef.current?.focus();
  }, [open, planKey]);

  const price = review ? monthlyPrice(review.plan) : null;
  const priceId = price?.price_id ?? null;
  const needsPreview = review !== null && review.mode !== "checkout" && previewProration !== undefined;

  useEffect(() => {
    if (!needsPreview || !priceId || priceId in previews) return;
    let cancelled = false;
    setLoadingPreview(true);
    previewProration!(priceId)
      .then((p) => {
        if (!cancelled) setPreviews((prev) => ({ ...prev, [priceId]: p }));
      })
      .catch(() => {
        if (!cancelled) setPreviews((prev) => ({ ...prev, [priceId]: null }));
      })
      .finally(() => {
        if (!cancelled) setLoadingPreview(false);
      });
    return () => {
      cancelled = true;
    };
  }, [needsPreview, priceId, previews, previewProration]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
      }
    },
    [onCancel],
  );

  if (!review) return null;

  const card = rates ?? DEFAULT_RATE_CARD;
  const seats = seatEstimate(review.plan, members, card);
  const previewLoading = needsPreview && priceId !== null && !(priceId in previews);
  const due = dueToday({
    mode: review.mode,
    price,
    proration: priceId ? (previews[priceId] ?? null) : null,
    loadingPreview: previewLoading || loadingPreview,
    currentPeriodEnd,
  });
  const canConfirm = priceId !== null && !busy && due.kind !== "loading";
  const planName = review.plan.name || review.plan.tier;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 !ml-0"
      onClick={onCancel}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="plan-review-title"
        data-testid="plan-review-dialog"
        className="w-[460px] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-2rem)] overflow-y-auto rounded-[14px] bg-[var(--color-bg-card)] border border-[var(--color-border)] shadow-2xl animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-[var(--color-border)]">
          <span id="plan-review-title" className="text-[13px] font-medium text-[var(--color-text)]">
            Review your plan
          </span>
          <span className="ml-2 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
            {review.mode === "downgrade" ? "downgrade to" : review.mode === "upgrade" ? "upgrade to" : ""} {planName}
          </span>
        </div>

        <div className="px-5">
          <Step n={1} title="plan">
            <p data-testid="review-fee" className="text-[12px] text-[var(--color-text)] font-mono tabular-nums">
              {planName} · {feeLine(review.plan)}
            </p>
            {price === null && (
              <p className="mt-1 text-[11px] text-[var(--color-error)]">this plan has no published price yet.</p>
            )}
          </Step>

          <Step n={2} title="seats">
            <div data-testid="review-seats" className="space-y-1">
              {seatLines(seats).map((line) => (
                <p key={line} className="text-[12px] text-[var(--color-text-muted)] leading-relaxed">
                  {line}
                </p>
              ))}
            </div>
          </Step>

          <Step n={3} title="included">
            <p data-testid="review-included" className="text-[12px] text-[var(--color-text-muted)] leading-relaxed">
              {includedLine(review.plan)}
            </p>
          </Step>

          <Step n={4} title="beyond that">
            <p className="text-[12px] text-[var(--color-text-muted)] leading-relaxed mb-1">
              Beyond that, usage is paid in credits at fixed rates.
            </p>
            <RateExpander rates={card} enterprise={review.plan.tier === "enterprise"} />
          </Step>

          <Step n={5} title={due.label}>
            <div data-testid="review-due" className="flex items-baseline justify-between gap-3">
              {due.kind === "loading" ? (
                <span className="inline-flex items-center gap-2 text-[11px] text-[var(--color-text-dim)]">
                  <Loader2 className="w-3 h-3 animate-spin" /> calculating...
                </span>
              ) : due.kind === "renewal" ? (
                <span className="text-[12px] text-[var(--color-text-muted)]">
                  {due.label}; {due.detail}
                </span>
              ) : (
                <>
                  <span className="text-[12px] text-[var(--color-text-dim)]">
                    {due.kind === "prorated" && due.creditCents > 0
                      ? `after a ${formatPrice(due.creditCents, due.currency)} credit from your current plan`
                      : "the monthly flat fee"}
                  </span>
                  <span className="text-[15px] font-medium font-mono tabular-nums text-[var(--color-text)]">
                    {formatPrice(due.amountCents, due.currency)}
                  </span>
                </>
              )}
            </div>
          </Step>
        </div>

        <div className="px-5 py-3 border-t border-[var(--color-border)] flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-[10px] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)]"
          >
            Cancel
          </button>
          <button
            ref={primaryRef}
            type="button"
            data-testid="review-primary"
            disabled={!canConfirm}
            onClick={() => {
              if (priceId) onConfirm(priceId);
            }}
            className="px-4 py-2 rounded-[10px] text-[12px] font-medium bg-[var(--color-text)] text-[var(--color-bg)] hover:opacity-90 disabled:opacity-40 transition-opacity duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-card)]"
          >
            {busy ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="w-3 h-3 animate-spin" /> redirecting...
              </span>
            ) : (
              primaryButtonLabel(review.mode)
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
