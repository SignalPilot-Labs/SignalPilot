"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Terminal,
  Database,
  ScrollText,
  Settings,
  Search,
  Table2,
  Activity,
} from "lucide-react";

const nav = [
  { href: "/dashboard", label: "dashboard", icon: LayoutDashboard, shortcut: "1" },
  { href: "/query", label: "query", icon: Search, shortcut: "2" },
  { href: "/schema", label: "schema", icon: Table2, shortcut: "3" },
  { href: "/sandboxes", label: "sandboxes", icon: Terminal, shortcut: "4" },
  { href: "/connections", label: "connections", icon: Database, shortcut: "5" },
  { href: "/health", label: "health", icon: Activity, shortcut: "6" },
  { href: "/audit", label: "audit", icon: ScrollText, shortcut: "7" },
  { href: "/settings", label: "settings", icon: Settings, shortcut: "8" },
];

function SignalPilotLogo() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Outer frame */}
      <rect x="1" y="1" width="30" height="30" fill="white" />
      <rect x="2" y="2" width="28" height="28" fill="black" />
      {/* Terminal chevron */}
      <path
        d="M8 9L14 16L8 23"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="square"
        strokeLinejoin="miter"
      />
      {/* Cursor line */}
      <line x1="16" y1="23" x2="24" y2="23" stroke="white" strokeWidth="2.5" strokeLinecap="square" />
      {/* Signal dot */}
      <circle cx="24" cy="9" r="2" fill="#00ff88" />
    </svg>
  );
}

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-[var(--color-sidebar)] border-r border-[var(--color-border)] flex flex-col z-50">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-[var(--color-border)]">
        <Link href="/dashboard" className="flex items-center gap-3 group">
          <div className="transition-transform group-hover:scale-105">
            <SignalPilotLogo />
          </div>
          <div>
            <h1 className="text-[11px] font-bold tracking-[0.2em] uppercase text-[var(--color-text)]">
              SignalPilot
            </h1>
            <p className="text-[9px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase mt-0.5">
              governed infra
            </p>
          </div>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {nav.map(({ href, label, icon: Icon, shortcut }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`group flex items-center gap-3 px-3 py-2 text-xs transition-all ${
                active
                  ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
                  : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
              }`}
            >
              <Icon className="w-3.5 h-3.5 flex-shrink-0" strokeWidth={active ? 2 : 1.5} />
              <span className="flex-1 tracking-wide">{label}</span>
              <span className={`text-[9px] tracking-wider ${active ? "text-[var(--color-text-dim)]" : "text-transparent group-hover:text-[var(--color-text-dim)]"} transition-colors`}>
                ^{shortcut}
              </span>
            </Link>
          );
        })}
      </nav>

      {/* Status footer */}
      <div className="px-4 py-3 border-t border-[var(--color-border)]">
        <div className="flex items-center gap-2 text-[10px] text-[var(--color-text-dim)]">
          <span className="w-1.5 h-1.5 bg-[var(--color-success)] pulse-dot" />
          <span className="tracking-[0.15em] uppercase">governance active</span>
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider">
            v0.1.0
          </span>
          <span className="text-[9px] text-[var(--color-text-dim)] tracking-wider px-1.5 py-0.5 border border-[var(--color-border)]">
            byof
          </span>
        </div>
      </div>
    </aside>
  );
}
