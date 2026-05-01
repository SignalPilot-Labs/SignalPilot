import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, body, action }: EmptyStateProps) {
  return (
    <section
      className="flex flex-col items-center justify-center py-16 px-8 text-center border border-[var(--color-border)] bg-[var(--color-bg-card)]"
    >
      {icon && (
        <div className="mb-4 text-[var(--color-text-dim)] animate-float">
          {icon}
        </div>
      )}
      <h2 className="text-base font-light tracking-wide text-[var(--color-text)] mb-2">{title}</h2>
      <p className="text-sm text-[var(--color-text-muted)] max-w-sm">{body}</p>
      {action && (
        <div className="mt-6">
          {action}
        </div>
      )}
    </section>
  );
}
