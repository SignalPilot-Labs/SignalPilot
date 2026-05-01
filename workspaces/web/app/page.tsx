export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-3xl font-semibold text-fg mb-4">Workspaces</h1>
      <p className="text-muted text-center max-w-md">
        Navigate to{" "}
        <code className="rounded bg-surface px-1.5 py-0.5 text-sm font-mono">
          /dashboards/&lt;workspace-id&gt;
        </code>{" "}
        to view charts for a workspace.
      </p>
    </main>
  );
}
