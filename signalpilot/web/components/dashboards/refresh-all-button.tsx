"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { refreshAllCharts } from "@/lib/dashboards/refresh-chart";

export function RefreshAllButton({ dashboardId }: { dashboardId: string }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function handleRefresh() {
    startTransition(async () => {
      await refreshAllCharts(dashboardId);
      router.refresh();
    });
  }

  return (
    <button
      onClick={handleRefresh}
      disabled={isPending}
      className="px-3 py-1.5 text-[12px] uppercase tracking-[0.15em] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all disabled:opacity-40 flex items-center gap-1.5"
    >
      <svg
        width="12"
        height="12"
        viewBox="0 0 12 12"
        fill="none"
        className={isPending ? "animate-spin" : ""}
      >
        <path
          d="M10 6A4 4 0 1 1 6 2"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
        />
        <path d="M6 0L8 2L6 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {isPending ? "refreshing..." : "refresh all"}
    </button>
  );
}
