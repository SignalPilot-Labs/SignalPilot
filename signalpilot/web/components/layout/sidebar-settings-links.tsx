"use client";

/** Settings sub-links rendered under the sidebar's settings group. */

import Link from "next/link";
import { KeyRound, CreditCard, Plug, PlugZap, BarChart3, Shield, Lock, Users, GitBranch, BookOpen } from "lucide-react";
import { useAppAuth } from "~/lib/auth-context";
import { useSubscription } from "~/lib/subscription-context";
import { usePermissions } from "~/lib/hooks/use-permissions";

/** API Keys nav link — available in both local and cloud mode */
export function ApiKeysNavLink({ pathname }: { pathname: string }) {
  const active = pathname.startsWith("/settings/api-keys");

  return (
    <Link
      href="/settings/api-keys"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
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

/** Billing nav link — cloud mode, org admins only */
export function BillingNavLink({ pathname }: { pathname: string }) {
  const { isCloudMode } = useAppAuth();
  const { can } = usePermissions();

  if (!isCloudMode || !can("billing.manage")) return null;

  const active = pathname.startsWith("/settings/billing");

  return (
    <Link
      href="/settings/billing"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <CreditCard size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">plans</span>
    </Link>
  );
}

/** Usage nav link — cloud mode; members land on "my usage" at the same route */
export function UsageNavLink({ pathname }: { pathname: string }) {
  const { isCloudMode } = useAppAuth();
  const { can } = usePermissions();

  if (!isCloudMode) return null;

  const active = pathname.startsWith("/settings/usage");
  const label = can("usage.org") ? "usage" : "my usage";

  return (
    <Link
      href="/settings/usage"
      aria-label="view usage analytics"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <BarChart3 size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">{label}</span>
    </Link>
  );
}

/** Connectors nav link — external tool servers for the chat agent */
export function ConnectorsNavLink({ pathname }: { pathname: string }) {
  const active = pathname.startsWith("/settings/connectors");

  return (
    <Link
      href="/settings/connectors"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <PlugZap size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">Connectors</span>
    </Link>
  );
}

/** MCP Connect nav link — org admins only (MCP-agent and chat defaults) */
export function McpConnectNavLink({ pathname }: { pathname: string }) {
  const { can } = usePermissions();
  const active = pathname.startsWith("/settings/mcp-connect");
  if (!can("settings.write")) return null;

  return (
    <Link
      href="/settings/mcp-connect"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
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

/** Notion Connect nav link — available in both local and cloud mode */
export function NotionConnectNavLink({ pathname }: { pathname: string }) {
  const active = pathname.startsWith("/settings/notion-connect");

  return (
    <Link
      href="/settings/notion-connect"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <BookOpen size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">notion connect</span>
    </Link>
  );
}

export function ByokNavLink({ pathname }: { pathname: string }) {
  const { isCloudMode } = useAppAuth();
  const { isLoaded, isBillable } = useSubscription();
  const { can } = usePermissions();
  // BYOK is on for every billable plan; hidden until the entitlement row is
  // loaded, and hidden from members (org admins manage keys).
  if (!isCloudMode || !isLoaded || !isBillable || !can("byok.manage")) return null;

  const active = pathname.startsWith("/settings/byok");

  return (
    <Link
      href="/settings/byok"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
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

/** Team nav link — cloud mode, org admins only */
export function TeamNavLink({ pathname }: { pathname: string }) {
  const { isCloudMode } = useAppAuth();
  const { can } = usePermissions();

  if (!isCloudMode || !can("team.manage")) return null;

  const active = pathname.startsWith("/settings/team");

  return (
    <Link
      href="/settings/team"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <Users size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">team</span>
    </Link>
  );
}

/** Account Security nav link — cloud-mode only */
export function AccountSecurityNavLink({ pathname }: { pathname: string }) {
  const { isCloudMode } = useAppAuth();

  if (!isCloudMode) return null;

  const active = pathname.startsWith("/settings/account-security");

  return (
    <Link
      href="/settings/account-security"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <Lock size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">account security</span>
    </Link>
  );
}

/** GitHub nav link — nested under settings */
export function GitHubNavLink({ pathname }: { pathname: string }) {
  const active = pathname.startsWith("/settings/github");

  return (
    <Link
      href="/settings/github"
      className={`group flex items-center gap-3 pl-9 pr-3 py-1.5 rounded-[10px] text-[12.5px] transition-colors duration-150 ${
        active
          ? "nav-active text-[var(--color-text)] bg-[var(--color-bg-hover)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
      }`}
    >
      <GitBranch size={11} className="flex-shrink-0 text-[var(--color-text-dim)]" />
      <span className="flex-1 tracking-wide text-[12px]">github</span>
    </Link>
  );
}
