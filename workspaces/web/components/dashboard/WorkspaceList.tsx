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
            className="block rounded-control border border-border bg-surface p-4 hover:bg-hover transition-colors"
          >
            <span className="font-mono text-sm text-fg">{id}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
