"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import dynamic from "next/dynamic";
import { LayoutGrid, BarChart3, Terminal, Database } from "lucide-react";
import { shouldHideSidebar } from "@/lib/sidebar-visibility";

const nav = [
  { href: "/dashboards", label: "dashboards", Icon: LayoutGrid, shortcut: "1" },
  { href: "/charts", label: "charts", Icon: BarChart3, shortcut: "2" },
  { href: "/agent-runs", label: "agent runs", Icon: Terminal, shortcut: "3" },
  { href: "/dbt-links", label: "dbt links", Icon: Database, shortcut: "4" },
] as const;

/**
 * Clerk UserButton — dynamically imported with ssr:false, cloud-only.
 * Only mounted when NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud".
 */
const ClerkUserButton = dynamic(
  () => import("@clerk/nextjs").then((m) => m.UserButton),
  { ssr: false }
);

const isCloud = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

export default function Sidebar() {
  const pathname = usePathname();

  if (shouldHideSidebar(pathname)) {
    return null;
  }

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-[var(--color-sidebar)] border-r border-[var(--color-border)] flex flex-col z-50">
      {/* Brand */}
      <div className="px-5 py-5 border-b border-[var(--color-border)]">
        <Link href="/dashboards" className="flex items-center gap-3 group">
          <div className="w-8 h-8 border border-[var(--color-border)] flex items-center justify-center flex-shrink-0 group-hover:border-[var(--color-border-hover)] transition-colors">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="1" width="6" height="6" stroke="var(--color-success)" strokeWidth="1" />
              <rect x="9" y="1" width="6" height="3" stroke="var(--color-text-dim)" strokeWidth="1" />
              <rect x="9" y="6" width="6" height="9" stroke="var(--color-text-dim)" strokeWidth="1" />
              <rect x="1" y="9" width="6" height="6" stroke="var(--color-text-dim)" strokeWidth="1" />
            </svg>
          </div>
          <div>
            <h1 className="text-[13px] font-bold tracking-[0.2em] uppercase leading-none text-[var(--color-text)]">
              WORKSPACES
            </h1>
            <p className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase mt-0.5">
              by signalpilot
            </p>
          </div>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {nav.map(({ href, label, Icon, shortcut }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`group flex items-center gap-3 px-3 py-2 text-sm transition-all ${
                active
                  ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
                  : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
              }`}
            >
              <Icon size={14} className="flex-shrink-0" />
              <span className="flex-1 tracking-wide">{label}</span>
              <span
                className={`text-[11px] tracking-wider ${
                  active
                    ? "text-[var(--color-text-dim)]"
                    : "text-transparent group-hover:text-[var(--color-text-dim)]"
                } transition-colors`}
              >
                ^{shortcut}
              </span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-[var(--color-border)] space-y-2">
        {/* Cloud UserButton */}
        {isCloud && (
          <div className="flex items-center gap-2 py-1">
            <ClerkUserButton />
          </div>
        )}

        {/* Status indicator */}
        <div className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
          <span className="w-1.5 h-1.5 bg-[var(--color-success)] pulse-dot inline-block" />
          <span>ready</span>
        </div>

        {/* Version */}
        <div className="text-[10px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase">
          v0.1.0
        </div>
      </div>
    </aside>
  );
}
