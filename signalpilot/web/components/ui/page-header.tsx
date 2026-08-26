"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Consistent page header. Sans-serif chrome, optional tab row for sections
 * that span multiple routes (e.g. Connections ↔ Health). See UX.md.
 */
export function PageHeader({
  title,
  subtitle,
  description,
  actions,
  tabs,
}: {
  title: string;
  subtitle: string;
  description: string;
  actions?: React.ReactNode;
  tabs?: { label: string; href: string }[];
}) {
  const pathname = usePathname();
  return (
    <div className="mb-8">
      {/* Title row */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1.5">
            <h1 className="text-[22px] font-semibold tracking-[-0.01em] leading-none text-[var(--color-text)]">
              {title}
            </h1>
            <span className="px-2 py-0.5 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[10.5px] leading-4 uppercase tracking-[0.08em] text-[var(--color-text-dim)]">
              {subtitle}
            </span>
          </div>
          <p className="text-[13px] text-[var(--color-text-muted)]">{description}</p>
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>

      {tabs && tabs.length > 0 && (
        <div className="mt-5 flex items-center gap-1">
          {tabs.map((t) => {
            const active = pathname === t.href || pathname.startsWith(`${t.href}/`);
            return (
              <Link
                key={t.href}
                href={t.href}
                className={`px-3.5 py-1.5 rounded-full text-[12.5px] font-medium transition-colors ${
                  active
                    ? "bg-[var(--color-bg-elevated)] border border-[var(--color-border-hover)] text-[var(--color-text)]"
                    : "border border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
                }`}
              >
                {t.label}
              </Link>
            );
          })}
        </div>
      )}

      <div className="mt-4 h-px bg-[var(--color-border)]" />
    </div>
  );
}

/**
 * Context bar under the page header: quiet mono caption carrying the governed
 * command context plus optional live status. (Formerly a terminal mock — the
 * CRT chrome is gone, the evidence-in-mono voice stays.)
 */
export function TerminalBar({
  path,
  status,
  children,
}: {
  path: string;
  status?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-6 rounded-[12px] border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
      <div className="px-4 py-2 flex items-center gap-3">
        <code className="text-[11.5px] text-[var(--color-text-dim)] flex-1">
          <span className="text-[var(--color-success)]">$</span>
          <span> signalpilot </span>
          <span className="text-[var(--color-text-muted)]">{path}</span>
        </code>
        {status}
      </div>
      {children && (
        <div className="px-4 py-2.5 flex items-center justify-between border-t border-[var(--color-border)]">
          {children}
        </div>
      )}
    </div>
  );
}

/** Shared tab set for the Connections section (Connections ↔ Health). */
export const CONNECTIONS_TABS = [
  { label: "Connections", href: "/connections" },
  { label: "Health", href: "/health" },
];
