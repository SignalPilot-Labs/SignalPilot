"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Terminal,
  Database,
  ScrollText,
  Settings,
  Zap,
  Search,
  Table2,
} from "lucide-react";

const nav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/query", label: "Query Explorer", icon: Search },
  { href: "/schema", label: "Schema Explorer", icon: Table2 },
  { href: "/sandboxes", label: "Sandboxes", icon: Terminal },
  { href: "/connections", label: "Connections", icon: Database },
  { href: "/audit", label: "Audit Log", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-screen w-60 bg-[var(--color-sidebar)] border-r border-[var(--color-border)] flex flex-col z-50">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-[var(--color-border)]">
        <div className="w-8 h-8 rounded-lg bg-[var(--color-accent)] flex items-center justify-center">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <div>
          <h1 className="text-sm font-semibold tracking-tight">SignalPilot</h1>
          <p className="text-[10px] text-[var(--color-text-muted)] uppercase tracking-wider">
            Sandbox Console
          </p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                active
                  ? "bg-[var(--color-accent)]/10 text-[var(--color-accent)]"
                  : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Status footer */}
      <div className="px-4 py-3 border-t border-[var(--color-border)] text-xs text-[var(--color-text-dim)] space-y-1">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-success)]" />
          <span>Governance Active</span>
        </div>
        <div>v0.1.0 &middot; BYOF Ready</div>
      </div>
    </aside>
  );
}
