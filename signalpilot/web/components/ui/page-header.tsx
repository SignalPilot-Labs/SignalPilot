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
    <div className="mb-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-lg sm:text-xl font-light tracking-wide text-[var(--color-text)]">{title}</h1>
            <span className="text-[12px] text-[var(--color-text-muted)] tracking-[0.15em] uppercase px-1.5 py-0.5 border border-[var(--color-border)] flex-shrink-0">
              {subtitle}
            </span>
          </div>
          <p className="text-sm text-[var(--color-text-muted)] tracking-wider">{description}</p>
        </div>
        {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
      </div>
      {/* Gradient accent line */}
      <div className="mt-3 sm:mt-4 h-px bg-gradient-to-r from-transparent via-[var(--color-border-hover)] to-transparent" />
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
      <div className="px-4 py-2 flex items-center gap-3 border-b border-[var(--color-border)] overflow-x-auto">
        {/* Terminal dots — hidden on mobile to save space */}
        <div className="hidden sm:flex items-center gap-1.5 flex-shrink-0">
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-30" />
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-20" />
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-10" />
        </div>
        {/* Path */}
        <code className="text-[12px] text-[var(--color-text-dim)] tracking-wider flex-1 whitespace-nowrap min-w-0 truncate">
          <span className="text-[var(--color-success)]">$</span>
          <span className="text-[var(--color-text-dim)] hidden sm:inline"> signalpilot </span>
          <span className="text-[var(--color-text-dim)] sm:hidden"> </span>
          <span className="text-[var(--color-text-muted)]">{path}</span>
        </code>
        {status && <span className="flex-shrink-0">{status}</span>}
      </div>
      {children && (
        <div className="px-4 py-2.5 flex items-center justify-between terminal-bar-content overflow-x-auto">
          <div className="flex items-center gap-4 min-w-0 flex-shrink-0">
            {children}
          </div>
          {/* Animated data flow indicator */}
          <div className="w-8 h-px ml-4 overflow-hidden opacity-30 flex-shrink-0 hidden sm:block">
            <div className="h-full animate-data-flow" />
          </div>
        </div>
      )}
    </div>
  );
}
