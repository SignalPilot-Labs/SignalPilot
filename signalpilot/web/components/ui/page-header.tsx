"use client";

/**
 * Consistent page header with terminal-style breadcrumb.
 */
export function PageHeader({
  title,
  subtitle,
  description,
  actions,
}: {
  title: string;
  subtitle: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between mb-8">
      <div>
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-lg font-light tracking-wide text-[var(--color-text)]">{title}</h1>
          <span className="text-[9px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase">/ {subtitle}</span>
        </div>
        <p className="text-xs text-[var(--color-text-dim)] tracking-wider">{description}</p>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/**
 * Terminal-style command bar shown at top of pages.
 * Gives the "developer console" feel.
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
    <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
      <div className="px-4 py-2 flex items-center gap-3 border-b border-[var(--color-border)]">
        {/* Terminal dots */}
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-30" />
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-20" />
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-10" />
        </div>
        {/* Path */}
        <code className="text-[10px] text-[var(--color-text-dim)] tracking-wider flex-1">
          <span className="text-[var(--color-success)]">~</span>
          <span className="text-[var(--color-text-dim)]">/signalpilot/</span>
          <span className="text-[var(--color-text-muted)]">{path}</span>
        </code>
        {status}
      </div>
      {children && (
        <div className="px-4 py-3">
          {children}
        </div>
      )}
    </div>
  );
}
