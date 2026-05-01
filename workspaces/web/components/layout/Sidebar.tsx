"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { shouldHideSidebar } from "@/lib/sidebar-visibility";
import { Tooltip } from "@/components/ui/Tooltip";

/* ── Custom SVG nav icons ── */

function NavIconDashboard({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="5" height="5" stroke="currentColor" strokeWidth="1" />
      <rect x="8" y="1" width="5" height="3" stroke="currentColor" strokeWidth="1" />
      <rect x="8" y="6" width="5" height="7" stroke="currentColor" strokeWidth="1" />
      <rect x="1" y="8" width="5" height="5" stroke="currentColor" strokeWidth="1" />
      {active && <rect x="2" y="2" width="3" height="3" fill="var(--color-success)" />}
    </svg>
  );
}

function NavIconChart({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <line x1="2" y1="2" x2="2" y2="12" stroke="currentColor" strokeWidth="1" />
      <line x1="2" y1="12" x2="12" y2="12" stroke="currentColor" strokeWidth="1" />
      <polyline points="4,9 6,6 8,7 10,4 12,5" stroke="currentColor" strokeWidth="1" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {active && <circle cx="12" cy="5" r="1.5" fill="var(--color-success)" />}
    </svg>
  );
}

function NavIconTerminal({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="12" height="12" stroke="currentColor" strokeWidth="1" />
      <path d="M3 5L5 7L3 9" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      <line x1="6" y1="9" x2="10" y2="9" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      {active && <rect x="11" y="2" width="2" height="2" fill="var(--color-success)" />}
    </svg>
  );
}

function NavIconDatabase({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <ellipse cx="7" cy="3" rx="5" ry="2" stroke="currentColor" strokeWidth="1" />
      <path d="M2 3V11C2 12.1 4.24 13 7 13C9.76 13 12 12.1 12 11V3" stroke="currentColor" strokeWidth="1" />
      <path d="M2 7C2 8.1 4.24 9 7 9C9.76 9 12 8.1 12 7" stroke="currentColor" strokeWidth="0.75" />
      {active && <line x1="4" y1="12" x2="10" y2="12" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" />}
    </svg>
  );
}

type NavIconComponent = React.FC<{ active: boolean }>;

const nav: { href: string; label: string; icon: NavIconComponent; shortcut: string }[] = [
  { href: "/dashboards", label: "dashboards", icon: NavIconDashboard, shortcut: "1" },
  { href: "/charts", label: "charts", icon: NavIconChart, shortcut: "2" },
  { href: "/agent-runs", label: "agent runs", icon: NavIconTerminal, shortcut: "3" },
  { href: "/dbt-links", label: "dbt links", icon: NavIconDatabase, shortcut: "4" },
];

/* ── Uptime counter ── */

function UptimeCounter() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(interval);
  }, []);
  const h = Math.floor(elapsed / 3600);
  const m = Math.floor((elapsed % 3600) / 60);
  const s = elapsed % 60;
  return (
    <span className="tabular-nums">
      {String(h).padStart(2, "0")}:{String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}
    </span>
  );
}

/* ── Clerk UserButton — dynamic import, cloud-only ── */

const ClerkUserButton = dynamic(
  () => import("@clerk/nextjs").then((m) => m.UserButton),
  { ssr: false }
);

const isCloud = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

/* ── Sidebar ── */

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.ctrlKey && !e.shiftKey && !e.altKey && !e.metaKey) {
        const idx = parseInt(e.key, 10);
        if (idx >= 1 && idx <= nav.length) {
          e.preventDefault();
          router.push(nav[idx - 1].href);
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router]);

  if (shouldHideSidebar(pathname)) {
    return null;
  }

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-[var(--color-sidebar)] border-r border-[var(--color-border)] flex flex-col z-50">
      {/* Brand */}
      <div className="px-5 py-5 border-b border-[var(--color-border)]">
        <Link href="/dashboards" className="flex items-center gap-3 group">
          <div className="w-8 h-8 border border-[var(--color-border)] flex items-center justify-center flex-shrink-0 group-hover:border-[var(--color-border-hover)] transition-colors">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
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

      {/* Command palette hint */}
      <div className="px-3 pt-4 pb-2">
        <button
          className="w-full flex items-center gap-2 px-3 py-1.5 border border-[var(--color-border)] hover:border-[var(--color-border-hover)] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)] transition-all tracking-wider"
          onClick={() => {
            window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }));
          }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0" aria-hidden="true">
            <circle cx="5" cy="5" r="3.5" stroke="currentColor" strokeWidth="1" />
            <path d="M8 8L10.5 10.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
          </svg>
          <span className="flex-1 text-left">search</span>
          <kbd className="px-1 py-0.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[10px] font-mono">
            ctrl+K
          </kbd>
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-2 space-y-0.5">
        {nav.map(({ href, label, icon: Icon, shortcut }) => {
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
              <Icon active={active} />
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

      {/* Status footer */}
      <div className="px-4 py-3 border-t border-[var(--color-border)] space-y-2.5">
        {/* Ready indicator */}
        <Tooltip content="workspaces gateway is healthy" position="right">
          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] cursor-default">
            <span className="w-1.5 h-1.5 bg-[var(--color-success)] pulse-dot inline-block flex-shrink-0" />
            <span className="tracking-[0.15em] uppercase leading-none">ready</span>
          </div>
        </Tooltip>

        {/* Uptime */}
        <Tooltip content="session uptime since page load" position="right">
          <div className="flex items-center gap-2 text-[11px] text-[var(--color-text-dim)] cursor-default">
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
              <circle cx="5" cy="5" r="4" stroke="var(--color-border-hover)" strokeWidth="1" fill="none" />
              <path d="M5 2.5V5L6.5 6.5" stroke="var(--color-text-dim)" strokeWidth="0.8" strokeLinecap="round" />
            </svg>
            <span className="tracking-wider leading-none">uptime <UptimeCounter /></span>
          </div>
        </Tooltip>

        {/* Separator */}
        <div className="separator-subtle" />

        {/* Bottom row: version + Clerk avatar */}
        <div className="flex items-center justify-between">
          <Tooltip content="workspaces version" position="right">
            <div className="flex items-center gap-1.5 cursor-default">
              <svg width="8" height="8" viewBox="0 0 8 8" fill="none" aria-hidden="true">
                <path d="M1 4H3L4 2L5 6L6 4H7" stroke="var(--color-text-dim)" strokeWidth="0.75" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
                v0.1.0
              </span>
            </div>
          </Tooltip>

          {isCloud && (
            <div className="flex items-center">
              <ClerkUserButton />
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
