"use client";

import { SWRConfig } from "swr";
import type { ReactNode } from "react";

/**
 * Global SWR provider with default cache settings.
 *
 * - dedupingInterval: 5s — dedupes identical requests within 5s
 * - revalidateOnFocus: false — don't refetch on tab focus (noisy)
 * - revalidateIfStale: true — background revalidate if data is stale
 * - errorRetryCount: 2 — retry failed requests twice
 */
export function SWRProvider({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        dedupingInterval: 5000,
        revalidateOnFocus: false,
        revalidateIfStale: true,
        errorRetryCount: 2,
      }}
    >
      {children}
    </SWRConfig>
  );
}
