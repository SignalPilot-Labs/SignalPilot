import Link from "next/link";

interface WorkspaceListProps {
  items: string[];
}

function DashboardIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="1" y="1" width="6" height="6" stroke="currentColor" strokeWidth="1" />
      <rect x="9" y="1" width="6" height="3" stroke="currentColor" strokeWidth="1" />
      <rect x="9" y="6" width="6" height="9" stroke="currentColor" strokeWidth="1" />
      <rect x="1" y="9" width="6" height="6" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

export function WorkspaceList({ items }: WorkspaceListProps) {
  return (
    <ul className="flex flex-col gap-2 stagger-fade-in" data-testid="workspace-list">
      {items.map((id) => (
        <li key={id}>
          <Link
            href={`/dashboards/${id}`}
            className="card-radial-glow group flex items-center gap-3 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 hover:bg-[var(--color-bg-hover)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-success)]"
          >
            <div className="flex-shrink-0 text-[var(--color-text-dim)]">
              <DashboardIcon />
            </div>
            <div className="flex-1 min-w-0">
              <span className="font-mono text-sm text-[var(--color-text)]">{id}</span>
              <p className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase mt-0.5">
                workspace
              </p>
            </div>
            <span className="text-transparent group-hover:text-[var(--color-text-dim)] transition-colors flex-shrink-0">
              →
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
