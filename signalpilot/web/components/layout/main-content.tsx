"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { isChromelessRoute } from "~/lib/route-chrome";

/** Offsets the page for the sidebar, except on routes that render without it. */
export function MainContent({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const fullWidth = isChromelessRoute(pathname);

  return (
    <main className={`${fullWidth ? "" : "md:ml-56"} min-h-screen relative z-10`}>
      {children}
    </main>
  );
}
