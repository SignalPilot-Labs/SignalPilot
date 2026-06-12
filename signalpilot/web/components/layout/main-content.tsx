"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** Routes where the sidebar is hidden — main content should be full-width. */
const FULL_WIDTH_PREFIXES = ["/sign-in", "/sign-up", "/onboarding", "/notebook"];

function matchesRoutePrefix(pathname: string, prefix: string) {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function MainContent({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const fullWidth = FULL_WIDTH_PREFIXES.some((prefix) => matchesRoutePrefix(pathname, prefix));

  return (
    <main className={`${fullWidth ? "" : "ml-56"} min-h-screen relative z-10`}>
      {children}
    </main>
  );
}
