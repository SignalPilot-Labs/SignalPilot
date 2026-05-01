import Link from "next/link";

interface WorkspaceListProps {
  items: string[];
}

export function WorkspaceList({ items }: WorkspaceListProps) {
  return (
    <ul className="flex flex-col gap-2" data-testid="workspace-list">
      {items.map((id) => (
        <li key={id}>
          <Link
            href={`/dashboards/${id}`}
            className="block border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 hover:bg-[var(--color-bg-hover)] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-success)]"
          >
            <span className="font-mono text-sm text-[var(--color-text)]">{id}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
