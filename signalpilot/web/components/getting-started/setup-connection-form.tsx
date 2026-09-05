"use client";

import { useEffect, useState } from "react";
import { ConnectionEditor } from "~/components/connections/editor/connection-editor";
import { useConnectionsController } from "~/components/connections/hooks/use-connections-controller";
import { updateWorkspaceProject } from "~/lib/api";

export function SetupConnectionForm({ projectId, onLinked }: { projectId: string; onLinked: (name: string) => void }) {
  const controller = useConnectionsController();
  const [linking, setLinking] = useState(false);
  const [pendingConnection, setPendingConnection] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);

  useEffect(() => {
    controller.setShowForm(true);
    controller.setForm((previous) => ({
      ...previous,
      tags: Array.from(new Set([...previous.tags, "sp-onboarding", "journey:setup-v2"])),
    }));
    // The controller owns the stable setters; this initialization belongs to this mounted step.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const existing = controller.connections.find((connection) =>
      connection.tags?.includes("sp-onboarding") &&
      connection.tags?.includes("journey:setup-v2"),
    );
    if (existing) setPendingConnection(existing.name);
  }, [controller.connections]);

  async function linkConnection(connectionName: string) {
    setLinking(true);
    setLinkError(null);
    try {
      await updateWorkspaceProject(projectId, { connection_name: connectionName });
      setPendingConnection(null);
      onLinked(connectionName);
    } catch (reason) {
      setPendingConnection(connectionName);
      setLinkError(reason instanceof Error ? reason.message : "The connection was saved, but linking failed.");
    } finally {
      setLinking(false);
    }
  }

  async function testAndLink() {
    const tested = await controller.handlePreTest();
    if (!tested || tested.status !== "healthy") return;
    const connection = await controller.handleCreate();
    if (!connection) return;
    await linkConnection(connection.name);
  }

  if (pendingConnection) {
    return (
      <div className="space-y-3 border border-[var(--color-border)] p-4">
        <p className="text-xs text-[var(--color-text)]">Connection “{pendingConnection}” was created successfully.</p>
        {linkError && <p role="alert" className="text-xs text-[var(--color-error)]">{linkError}</p>}
        <button type="button" disabled={linking} onClick={() => void linkConnection(pendingConnection)} className="bg-[var(--color-text)] px-4 py-2 text-xs text-[var(--color-bg)] disabled:opacity-40">
          {linking ? "Linking…" : "Retry linking"}
        </button>
      </div>
    );
  }

  return (
    <ConnectionEditor
      controller={controller}
      primaryAction={{ label: "Test and link", onClick: testAndLink, pending: linking }}
    />
  );
}
