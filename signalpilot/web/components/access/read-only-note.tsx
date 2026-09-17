"use client";

import { Lock } from "lucide-react";

/**
 * The line a member sees where an org-level editor would be. Inline by
 * default; `block` renders it as a small card for a whole form.
 */
export function ReadOnlyNote({
  children,
  block = false,
  className,
}: {
  /** Optional detail after the fixed lead: "connection credentials stay redacted". */
  children?: React.ReactNode;
  block?: boolean;
  className?: string;
}) {
  const body = (
    <>
      <Lock className="w-3 h-3 flex-shrink-0" strokeWidth={1.5} />
      <span>
        Managed by your org admins
        {children ? <span className="text-[var(--color-text-dim)]"> · {children}</span> : null}
      </span>
    </>
  );
  if (block) {
    return (
      <div
        data-testid="read-only-note"
        className={`flex items-center gap-2 px-3 py-2 border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[10px] text-[12px] text-[var(--color-text-muted)] ${className ?? ""}`}
      >
        {body}
      </div>
    );
  }
  return (
    <span
      data-testid="read-only-note"
      className={`inline-flex items-center gap-1.5 text-[11.5px] text-[var(--color-text-muted)] ${className ?? ""}`}
    >
      {body}
    </span>
  );
}
