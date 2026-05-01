interface EmptyStateProps {
  title: string;
  body: string;
}

export function EmptyState({ title, body }: EmptyStateProps) {
  return (
    <section
      role="status"
      className="rounded-card border border-border bg-surface p-6 shadow-card"
    >
      <h2 className="text-base font-semibold text-fg mb-2">{title}</h2>
      <p className="text-sm text-muted">{body}</p>
    </section>
  );
}
