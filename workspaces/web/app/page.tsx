import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex flex-col items-center justify-center p-8">
      <h1 className="text-3xl font-semibold text-fg mb-4">Workspaces</h1>
      <p className="text-muted">
        Browse <Link href="/dashboards" className="underline">dashboards</Link> to view charts for a workspace.
      </p>
    </main>
  );
}
