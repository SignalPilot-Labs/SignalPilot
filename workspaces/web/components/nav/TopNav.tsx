import Link from "next/link";

export function TopNav() {
  return (
    <header className="border-b border-border bg-surface">
      <nav className="flex items-center gap-6 px-6 py-3">
        <Link href="/" className="text-sm font-semibold text-fg">
          Workspaces
        </Link>
        <Link href="/dashboards" className="text-sm text-muted hover:text-fg transition-colors">
          Dashboards
        </Link>
        <Link href="/charts/new" className="text-sm text-muted hover:text-fg transition-colors">
          New chart
        </Link>
      </nav>
    </header>
  );
}
