"use client";

// The "set as org default" affordance next to the project picker. Anyone
// can pick a project for their own chat; only an admin can make it the
// org default. Members see the control disabled with the rule as tooltip.

import { Pin } from "lucide-react";
import { AdminOnlyControl } from "~/components/access/admin-only-control";
import { usePermissions } from "~/lib/hooks/use-permissions";

export function DefaultProjectControl({
  selectedProjectId,
  defaultProjectId,
  onSetDefault,
}: {
  selectedProjectId: string | null;
  defaultProjectId: string | null;
  onSetDefault: (projectId: string) => void;
}) {
  const { can } = usePermissions();
  if (!selectedProjectId) return null;
  if (selectedProjectId === defaultProjectId) {
    return (
      <span
        data-testid="chat-default-project-current"
        title="New chats in your org start on this project"
        className="inline-flex shrink-0 items-center gap-1 text-[10.5px] text-[var(--color-text-dim)]"
      >
        <Pin className="h-2.5 w-2.5" aria-hidden="true" />
        org default
      </span>
    );
  }
  return (
    <AdminOnlyControl permission="chat.default_project" allowed={can("chat.default_project")}>
      <button
        type="button"
        data-testid="chat-set-default-project"
        onClick={() => onSetDefault(selectedProjectId)}
        title="Use this project as the org default for new chats"
        className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[var(--color-border)] px-2 py-1 text-[10.5px] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
      >
        <Pin className="h-2.5 w-2.5" aria-hidden="true" />
        set as org default
      </button>
    </AdminOnlyControl>
  );
}
