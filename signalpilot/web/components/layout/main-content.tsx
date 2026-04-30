"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** Routes where the sidebar is hidden — main content should be full-width. */
const FULL_WIDTH_PREFIXES = ["/sign-in", "/sign-up", "/onboarding"];

export function MainContent({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const fullWidth = FULL_WIDTH_PREFIXES.some((p) => pathname.startsWith(p));

  return (
    <main className={`${fullWidth ? "" : "ml-56"} min-h-screen relative z-10`}>
      {children}
    </main>
  );
}
