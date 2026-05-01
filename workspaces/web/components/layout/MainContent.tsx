"use client";

import { usePathname } from "next/navigation";
import { PageTransition } from "@/components/ui/PageTransition";
import { shouldHideSidebar } from "@/lib/sidebar-visibility";

export function MainContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const hideSidebar = shouldHideSidebar(pathname);

  return (
    <main
      className={`relative z-10 min-h-screen ${hideSidebar ? "" : "ml-56"}`}
    >
      <PageTransition>{children}</PageTransition>
    </main>
  );
}
