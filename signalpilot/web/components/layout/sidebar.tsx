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

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-[var(--color-sidebar)] border-r border-[var(--color-border)] flex flex-col z-50">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-[var(--color-border)]">
        <div className="flex items-center gap-3">
          {/* Custom SVG Logo - Terminal/Signal inspired */}
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="28" height="28" fill="white"/>
            <path d="M7 8L13 14L7 20" stroke="black" strokeWidth="2.5" strokeLinecap="square"/>
            <line x1="15" y1="20" x2="22" y2="20" stroke="black" strokeWidth="2.5" strokeLinecap="square"/>
          </svg>
          <div>
            <h1 className="text-xs font-bold tracking-wider uppercase text-[var(--color-text)]">
              SignalPilot
            </h1>
            <p className="text-[9px] text-[var(--color-text-dim)] tracking-widest uppercase mt-0.5">
              governed infra
            </p>
          </div>
        </div>
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
                  ? "text-[var(--color-text)] bg-[var(--color-bg-hover)]"
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
          <span className="tracking-wider uppercase">governance active</span>
        </div>
        <div className="text-[9px] text-[var(--color-text-dim)] mt-1.5 tracking-wider">
          v0.1.0 / byof ready
        </div>
      </div>
    </aside>
  );
}
