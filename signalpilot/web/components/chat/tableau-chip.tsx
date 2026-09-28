"use client";

// "Tableau connected" chip in the chat composer. Shows only when the org's
// Tableau integration is active (configured, enabled, verified), so the
// person knows chat agents can reach the site. Fails silent: any error or
// a missing route keeps it hidden.

import { useEffect, useState } from "react";
import Link from "next/link";
import { getTableauIntegration } from "~/lib/api";
import { TableauIcon } from "~/components/branding/tableau-icon";

export const TABLEAU_CHIP_TOOLTIP =
  "Chat agents can use your Tableau site. Manage in Integrations.";

/** True once GET /api/tableau/integration answers `active: true`. One fetch per mount. */
export function useTableauActive(): boolean {
  const [active, setActive] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getTableauIntegration()
      .then((info) => {
        if (!cancelled) setActive(Boolean(info?.active));
      })
      .catch(() => {
        if (!cancelled) setActive(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return active;
}

export function TableauChip() {
  const active = useTableauActive();
  if (!active) return null;
  return (
    <Link
      href="/integrations#tableau"
      title={TABLEAU_CHIP_TOOLTIP}
      aria-label={`Tableau connected. ${TABLEAU_CHIP_TOOLTIP}`}
      data-testid="chat-tableau-chip"
      className="flex h-8 items-center gap-1.5 rounded-lg px-2 text-[12px] text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] focus-visible:ring-2 focus-visible:ring-[var(--color-text)]"
    >
      <TableauIcon className="h-3.5 w-3.5 text-[var(--color-success)]" />
      <span className="hidden sm:inline">Tableau connected</span>
    </Link>
  );
}
