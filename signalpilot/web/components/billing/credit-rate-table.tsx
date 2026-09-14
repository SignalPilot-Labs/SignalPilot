"use client";

import {
  DEFAULT_RATE_CARD,
  type RateCard,
  creditRatesFrom,
  creditsToUsd,
  formatCredits,
  formatUsd,
} from "~/lib/billing-rates";

/**
 * The fixed credit rate card. One credit is one cent, no volume brackets;
 * every plan pays the same rates beyond its allowances. `rates` is the card
 * published by `GET /api/v1/billing/plans`; the local fallback renders while
 * it loads.
 */
export function CreditRateTable({
  enterprise = false,
  rates,
}: {
  enterprise?: boolean;
  rates?: RateCard | null;
}) {
  const card = rates ?? DEFAULT_RATE_CARD;
  const rows = creditRatesFrom(card);
  const creditUsd = formatUsd(creditsToUsd(1, card));
  const overageUsd = formatUsd(card.overage_cents_per_credit / 100);
  return (
    <div
      data-testid="credit-rate-table"
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] overflow-hidden"
    >
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-[var(--color-border)] bg-[var(--color-bg)]">
            <th className="text-left px-5 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
              item
            </th>
            <th className="text-right px-5 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
              credits
            </th>
            <th className="text-right px-5 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
              usd
            </th>
            <th className="hidden md:table-cell text-left px-5 py-2 text-[11px] font-normal text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
              note
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((rate) => {
            const credits =
              enterprise && rate.enterpriseCredits !== undefined ? rate.enterpriseCredits : rate.credits;
            return (
              <tr key={rate.unit} className="border-b border-[var(--color-border)] last:border-b-0">
                <td className="px-5 py-2.5 text-[var(--color-text-muted)]">
                  {rate.label}
                  <span className="text-[var(--color-text-dim)]"> / {rate.per}</span>
                </td>
                <td className="px-5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text)]">
                  {credits === null ? `cost × ${card.token_credits_per_dollar}` : formatCredits(credits)}
                </td>
                <td className="px-5 py-2.5 text-right font-mono tabular-nums text-[var(--color-text-dim)]">
                  {credits === null ? "at cost" : formatUsd(creditsToUsd(credits, card))}
                </td>
                <td className="hidden md:table-cell px-5 py-2.5 text-[var(--color-text-dim)] leading-relaxed">
                  {rate.note}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="px-5 py-3 text-[11px] text-[var(--color-text-dim)] border-t border-[var(--color-border)]">
        1 credit = {creditUsd}. Credits beyond the monthly block are billed at {overageUsd} each on the next
        invoice; nothing is blocked. Guarantees put credits back: failed, low-evidence and flagged-wrong threads are never charged.
      </p>
    </div>
  );
}
