"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import dynamic from "next/dynamic";
import { KeyRound, CreditCard, Plug, BarChart3, Shield } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { useAppAuth } from "@/lib/auth-context";

/* Custom SVG nav icons — geometric, minimal, brutalism-lite */
function NavIconDashboard({ active }: { active: boolean }) {
  const s = active ? "currentColor" : "currentColor";
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1" y="1" width="5" height="5" stroke={s} strokeWidth="1" />
      <rect x="8" y="1" width="5" height="3" stroke={s} strokeWidth="1" />
      <rect x="8" y="6" width="5" height="7" stroke={s} strokeWidth="1" />
      <rect x="1" y="8" width="5" height="5" stroke={s} strokeWidth="1" />
    </svg>
  );
}
function NavIconQuery({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M2 3H12M2 7H8M2 11H10" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      <path d="M10 8L12 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square" />
      {active && <circle cx="11" cy="9" r="1" fill="var(--color-success)" />}
    </svg>
  );
}
function NavIconSchema({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1" y="1" width="12" height="12" stroke="currentColor" strokeWidth="1" />
      <line x1="1" y1="5" x2="13" y2="5" stroke="currentColor" strokeWidth="0.75" />
      <line x1="5" y1="1" x2="5" y2="13" stroke="currentColor" strokeWidth="0.75" />
    </svg>
  );
}
function NavIconProject({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M1 3L1 12H13V3H7L5 1H1V3Z" stroke="currentColor" strokeWidth="1" strokeLinejoin="miter" fill="none" />
      {active && <rect x="5" y="6" width="4" height="3" fill="var(--color-success)" />}
    </svg>
  );
}
function NavIconSandbox({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="1" y="1" width="12" height="12" stroke="currentColor" strokeWidth="1" />
      <path d="M4 5L6 7L4 9" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      <line x1="7" y1="9" x2="10" y2="9" stroke="currentColor" strokeWidth="1" strokeLinecap="square" />
      {active && <rect x="10" y="2" width="2" height="2" fill="var(--color-success)" />}
    </svg>
  );
}
function NavIconDatabase({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <ellipse cx="7" cy="3" rx="5" ry="2" stroke="currentColor" strokeWidth="1" />
      <path d="M2 3V11C2 12.1 4.24 13 7 13C9.76 13 12 12.1 12 11V3" stroke="currentColor" strokeWidth="1" />
      <path d="M2 7C2 8.1 4.24 9 7 9C9.76 9 12 8.1 12 7" stroke="currentColor" strokeWidth="0.75" />
    </svg>
  );
}
function NavIconHealth({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M1 7H3L5 3L7 11L9 5L11 7H13" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
      {active && <circle cx="7" cy="7" r="1" fill="var(--color-success)" />}
    </svg>
  );
}
function NavIconAudit({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <rect x="2" y="1" width="10" height="12" stroke="currentColor" strokeWidth="1" />
      <line x1="4" y1="4" x2="10" y2="4" stroke="currentColor" strokeWidth="0.75" />
      <line x1="4" y1="6.5" x2="10" y2="6.5" stroke="currentColor" strokeWidth="0.75" />
      <line x1="4" y1="9" x2="8" y2="9" stroke="currentColor" strokeWidth="0.75" />
    </svg>
  );
}
function NavIconSettings({ active }: { active: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="2.5" stroke="currentColor" strokeWidth="1" />
      <path d="M7 1V3M7 11V13M1 7H3M11 7H13M2.5 2.5L4 4M10 10L11.5 11.5M11.5 2.5L10 4M4 10L2.5 11.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="square" />
    </svg>
  );
}

type NavIconComponent = React.FC<{ active: boolean }>;

const nav: { href: string; label: string; icon: NavIconComponent; shortcut: string }[] = [
  { href: "/dashboard", label: "dashboard", icon: NavIconDashboard, shortcut: "1" },
  { href: "/connections", label: "connections", icon: NavIconDatabase, shortcut: "2" },
  { href: "/schema", label: "schema", icon: NavIconSchema, shortcut: "3" },
  { href: "/projects", label: "projects", icon: NavIconProject, shortcut: "4" },
  { href: "/sandboxes", label: "sandboxes", icon: NavIconSandbox, shortcut: "5" },
  { href: "/query", label: "query", icon: NavIconQuery, shortcut: "6" },
  { href: "/audit", label: "audit", icon: NavIconAudit, shortcut: "7" },
  { href: "/health", label: "health", icon: NavIconHealth, shortcut: "8" },
  { href: "/settings", label: "settings", icon: NavIconSettings, shortcut: "9" },
];

/** Routes where the sidebar should be hidden */
const AUTH_ROUTE_PREFIXES = ["/sign-in", "/sign-up"];

function SignalPilotLogo() {
  return (
    <div className="relative">
      {/* Status ring */}
      <svg width="38" height="38" viewBox="0 0 38 38" fill="none" className="absolute -inset-[3px]">
        <circle cx="19" cy="19" r="17" stroke="var(--color-border)" strokeWidth="0.5" fill="none" />
        <circle cx="19" cy="19" r="17" stroke="var(--color-success)" strokeWidth="1" fill="none"
          strokeDasharray="80 27" strokeLinecap="square" opacity="0.3"
          className="-rotate-90 origin-center"
        >
          <animateTransform attributeName="transform" type="rotate" from="0 19 19" to="360 19 19" dur="20s" repeatCount="indefinite" />
        </circle>
      </svg>
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
        {/* Signal dot with pulse */}
        <circle cx="24" cy="9" r="3" fill="#00ff88" opacity="0.15">
          <animate attributeName="r" values="3;5;3" dur="3s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.15;0;0.15" dur="3s" repeatCount="indefinite" />
        </circle>
        <circle cx="24" cy="9" r="2" fill="#00ff88" />
      </svg>
    </div>
  );
}

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

/* ── Badge for nav items ── */
function NavBadge({ count, color = "var(--color-success)" }: { count: number; color?: string }) {
  if (count <= 0) return null;
  return (
    <span
      className="flex items-center justify-center min-w-[14px] h-[14px] px-1 text-[10px] tabular-nums tracking-wider"
      style={{ backgroundColor: color, color: "var(--color-bg)" }}
    >
      {count}
    </span>
  );
}

/** User section rendered between nav links and status footer */
function UserSection() {
  const { clerkEnabled, isAuthenticated, user } = useAppAuth();

  if (!clerkEnabled) {
    // Local mode without Clerk — no auth UI, existing behavior
    return null;
  }

  if (isAuthenticated && user) {
    const displayName =
      [user.firstName, user.lastName].filter(Boolean).join(" ") ||
      user.email ||
      "user";

    return (
      <div className="px-3 py-2 border-t border-[var(--color-border)]">
        <ClerkUserButton displayName={displayName} />
      </div>
    );
  }

  // Clerk enabled but not signed in
  return (
    <div className="px-3 py-2 border-t border-[var(--color-border)]">
      <Link
        href="/sign-in"
        className="flex items-center gap-2 px-3 py-1.5 text-[12px] tracking-wider uppercase text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all"
      >
        <KeyRound size={12} className="flex-shrink-0" />
        <span>sign in</span>
      </Link>
    </div>
  );
}

/**
 * Thin wrapper around Clerk's UserButton — dynamically imported so
 * @clerk/nextjs is never loaded until ClerkProvider has mounted.
 */
const ClerkUserButton = dynamic(
  () => import("@/components/layout/clerk-user-button"),
  { ssr: false }
);

/** API Keys nav link — available in both local and cloud mode */
function ApiKeysNavLink({ pathname }: { pathname: string }) {
  const active = pathname.startsWith("/settings/api-keys");

  return (
    <Link
      href="/settings/api-keys"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 text-sm transition-all ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <KeyRound size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">api keys</span>
    </Link>
  );
}

/** Billing nav link — only rendered in cloud mode, nested under /settings */
function BillingNavLink({ pathname }: { pathname: string }) {
  const { isCloudMode } = useAppAuth();

  if (!isCloudMode) return null;

  const active = pathname.startsWith("/settings/billing");

  return (
    <Link
      href="/settings/billing"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 text-sm transition-all ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <CreditCard size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">billing</span>
    </Link>
  );
}

/** Usage nav link — only rendered in cloud mode, nested under /settings */
function UsageNavLink({ pathname }: { pathname: string }) {
  const { isCloudMode } = useAppAuth();

  if (!isCloudMode) return null;

  const active = pathname.startsWith("/settings/usage");

  return (
    <Link
      href="/settings/usage"
      aria-label="view usage analytics"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 text-sm transition-all ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <BarChart3 size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">usage</span>
    </Link>
  );
}

/** MCP Connect nav link — available in both local and cloud mode */
function McpConnectNavLink({ pathname }: { pathname: string }) {
  const active = pathname.startsWith("/settings/mcp-connect");

  return (
    <Link
      href="/settings/mcp-connect"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 text-sm transition-all ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <Plug size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">mcp connect</span>
    </Link>
  );
}

function ByokNavLink({ pathname }: { pathname: string }) {
  const active = pathname.startsWith("/settings/byok");

  return (
    <Link
      href="/settings/byok"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 text-sm transition-all ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <Shield size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">security</span>
    </Link>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [activeSandboxes, setActiveSandboxes] = useState(0);
  const [projectCount, setProjectCount] = useState(0);
  const [connHealth, setConnHealth] = useState<{ total: number; healthy: number }>({ total: 0, healthy: 0 });

  // Poll for active sandbox count and connection health
  const fetchCounts = useCallback(() => {
    const url = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";
    const key = typeof window !== "undefined" ? localStorage.getItem("sp_api_key") : null;
    const headers: Record<string, string> = {};
    if (key) headers["Authorization"] = `Bearer ${key}`;
    fetch(`${url}/api/sandboxes`, { headers })
      .then((r) => r.ok ? r.json() : [])
      .then((sandboxes: { status: string }[]) => {
        setActiveSandboxes(sandboxes.filter((s) => s.status === "running").length);
      })
      .catch(() => {});
    fetch(`${url}/api/projects`, { headers })
      .then((r) => r.ok ? r.json() : [])
      .then((projects: { status: string }[]) => {
        setProjectCount(projects.length);
      })
      .catch(() => {});
    fetch(`${url}/api/connections/health`, { headers })
      .then((r) => r.ok ? r.json() : { connections: [] })
      .then((data: { connections: { status: string }[] }) => {
        const conns = data.connections || [];
        setConnHealth({
          total: conns.length,
          healthy: conns.filter((c) => c.status === "healthy").length,
        });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchCounts();
    const i = setInterval(fetchCounts, 30000);
    return () => clearInterval(i);
  }, [fetchCounts]);

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

  // Hide sidebar on auth pages — checked after all hooks are called
  if (AUTH_ROUTE_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return null;
  }

  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-[var(--color-sidebar)] border-r border-[var(--color-border)] flex flex-col z-50">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-[var(--color-border)]">
        <Link href="/dashboard" className="flex items-center gap-3 group">
          <div className="transition-transform group-hover:scale-105">
            <SignalPilotLogo />
          </div>
          <div>
            <h1 className="text-[13px] font-bold tracking-[0.2em] uppercase text-[var(--color-text)]">
              SignalPilot
            </h1>
            <p className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase mt-0.5">
              governed infra
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
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
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
          const badge = href === "/sandboxes" ? activeSandboxes : href === "/projects" ? projectCount : 0;
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
              {badge > 0 ? (
                <NavBadge count={badge} />
              ) : (
                <span className={`text-[11px] tracking-wider ${active ? "text-[var(--color-text-dim)]" : "text-transparent group-hover:text-[var(--color-text-dim)]"} transition-colors`}>
                  ^{shortcut}
                </span>
              )}
            </Link>
          );
        })}
        {/* API Keys sub-link — cloud mode only */}
        <ApiKeysNavLink pathname={pathname} />
        {/* Usage sub-link — cloud mode only */}
        <UsageNavLink pathname={pathname} />
        {/* Billing sub-link — cloud mode only */}
        <BillingNavLink pathname={pathname} />
        {/* MCP Connect sub-link */}
        <McpConnectNavLink pathname={pathname} />
        {/* Security sub-link */}
        <ByokNavLink pathname={pathname} />
      </nav>

      {/* User section — Clerk UserButton or sign-in link */}
      <UserSection />

      {/* Status footer */}
      <div className="px-4 py-3 border-t border-[var(--color-border)] space-y-2.5">
        <Tooltip content="all governance guards are active" position="right">
          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] cursor-default">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full bg-[var(--color-success)] opacity-30" />
              <span className="relative inline-flex h-2 w-2 bg-[var(--color-success)]" />
            </span>
            <span className="tracking-[0.15em] uppercase">governance active</span>
          </div>
        </Tooltip>
        {connHealth.total > 0 && (
          <Tooltip content={`${connHealth.healthy}/${connHealth.total} connections healthy`} position="right">
            <Link href="/connections" className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)] transition-colors cursor-pointer">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <ellipse cx="5" cy="3" rx="3.5" ry="1.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
                <path d="M1.5 3V7C1.5 8 3.1 9 5 9C6.9 9 8.5 8 8.5 7V3" stroke="currentColor" strokeWidth="0.75" />
              </svg>
              <span className="tracking-[0.15em] uppercase">
                db {connHealth.healthy}/{connHealth.total}
              </span>
              {connHealth.healthy < connHealth.total && (
                <span className="w-1.5 h-1.5 bg-[var(--color-warning)]" />
              )}
            </Link>
          </Tooltip>
        )}
        <Tooltip content="session uptime since page load" position="right">
          <div className="flex items-center gap-3 text-[11px] text-[var(--color-text-dim)] cursor-default">
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <circle cx="5" cy="5" r="4" stroke="var(--color-border-hover)" strokeWidth="1" fill="none" />
              <path d="M5 2.5V5L6.5 6.5" stroke="var(--color-text-dim)" strokeWidth="0.8" strokeLinecap="round" />
            </svg>
            <span className="tracking-wider">uptime <UptimeCounter /></span>
          </div>
        </Tooltip>
        {/* System info line */}
        <div className="separator-subtle" />
        <div className="flex items-center justify-between">
          <Tooltip content="signalpilot gateway version" position="right">
            <div className="flex items-center gap-1.5 cursor-default">
              <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                <path d="M1 4H3L4 2L5 6L6 4H7" stroke="var(--color-text-dim)" strokeWidth="0.75" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
                v0.1.0
              </span>
            </div>
          </Tooltip>
          <Tooltip content="bring your own sandbox" position="left">
            <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider px-1.5 py-0.5 border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-colors cursor-default">
              byos
            </span>
          </Tooltip>
        </div>
      </div>
    </aside>
  );
}
