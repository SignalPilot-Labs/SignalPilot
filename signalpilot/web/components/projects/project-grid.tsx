"use client";

import { AlertTriangle, Cloud, Database, ExternalLink, Loader2, Settings, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { NotionIcon } from "~/components/branding/notion-icon";
import { useToast } from "~/components/ui/toast";
import {
  deleteWorkspaceProject,
} from "~/lib/api";
import type { WorkspaceProjectInfo } from "~/lib/types";
import { OUTLINE_BUTTON, ICON_BUTTON, type NotionConversation, getErrorMessage, formatBytes, formatRelativeTime, formatConversationTime } from "~/components/projects/projects-overview-shared";
import { usePermissions } from "~/lib/hooks/use-permissions";

export function ProjectGrid({
  projects,
  loading,
  projectCount,
  onProjectClick,
  onProjectSettings,
  onProjectDeleted,
}: {
  projects: WorkspaceProjectInfo[];
  loading: boolean;
  projectCount: number;
  onProjectClick: (project: WorkspaceProjectInfo) => void;
  onProjectSettings: (project: WorkspaceProjectInfo) => void;
  onProjectDeleted: () => void | Promise<void>;
}) {
  if (loading && projects.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-sm text-[var(--color-text-dim)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading projects...
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-[var(--color-text-dim)]">
        <Cloud className="mx-auto mb-2 h-6 w-6 opacity-40" />
        <p>No projects found.</p>
        {projectCount > 0 && (
          <p className="mt-1 text-xs">
            Workspace projects could not be listed, but legacy projects were
            detected.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {projects.map((project) => (
        <ProjectCard
          key={project.id}
          project={project}
          onClick={onProjectClick}
          onSettings={onProjectSettings}
          onDeleted={onProjectDeleted}
        />
      ))}
    </div>
  );
}

function ProjectCard({
  project,
  onClick,
  onSettings,
  onDeleted,
}: {
  project: WorkspaceProjectInfo;
  onClick: (project: WorkspaceProjectInfo) => void;
  onSettings: (project: WorkspaceProjectInfo) => void;
  onDeleted: () => void | Promise<void>;
}) {
  const { can } = usePermissions();
  const canDelete = can("projects.write");
  const [showDelete, setShowDelete] = useState(false);
  const tags = project.tags ?? [];
  const projectName = project.display_name || project.name;
  const details = [
    project.file_count > 0 ? `${project.file_count} files` : "",
    formatBytes(project.total_bytes),
    formatRelativeTime(project.updated_at),
  ].filter(Boolean);

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        className="group relative w-full rounded-lg border border-[var(--color-border)] p-4 text-left transition-all duration-150 hover:border-[var(--color-text-dim)] hover:bg-muted/50"
        onClick={() => onClick(project)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onClick(project);
          }
        }}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-md bg-primary/10 p-2 text-primary">
            <Cloud className="h-[18px] w-[18px]" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-[var(--color-text)]">
              {projectName}
            </div>
            {project.description && (
              <div className="mt-0.5 truncate text-xs text-[var(--color-text-dim)]">
                {project.description}
              </div>
            )}
            {project.connection_name && (
              <div className="mt-0.5 text-xs text-[var(--color-text-dim)]">
                <Database className="mr-1 inline h-2.5 w-2.5" />
                {project.connection_name}
              </div>
            )}
            {details.length > 0 && (
              <div className="mt-1.5 flex items-center gap-3 text-[10px] text-[var(--color-text-dim)]">
                {details.map((detail) => (
                  <span key={detail}>{detail}</span>
                ))}
              </div>
            )}
            {tags.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-[var(--color-text-dim)]"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        <button
          type="button"
          className="absolute right-10 top-2 rounded-md p-1.5 text-[var(--color-text-dim)] opacity-0 transition-opacity hover:bg-muted hover:text-[var(--color-text)] focus-visible:opacity-100 group-hover:opacity-100"
          onClick={(event) => {
            event.stopPropagation();
            onSettings(project);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              event.stopPropagation();
              onSettings(project);
            }
          }}
          aria-label={`Settings for ${projectName}`}
        >
          <Settings className="h-3.5 w-3.5" />
        </button>
        {canDelete && (
        <button
          type="button"
          className="absolute right-2 top-2 rounded-md p-1.5 text-[var(--color-text-dim)] opacity-0 transition-opacity hover:bg-[var(--color-error)]/10 hover:text-[var(--color-error)] group-hover:opacity-100"
          onClick={(event) => {
            event.stopPropagation();
            setShowDelete(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              event.stopPropagation();
              setShowDelete(true);
            }
          }}
          aria-label={`Delete ${projectName}`}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
        )}
      </div>

      {showDelete && (
        <DeleteProjectModal
          project={project}
          onClose={() => setShowDelete(false)}
          onDeleted={async () => {
            setShowDelete(false);
            await onDeleted();
          }}
        />
      )}
    </>
  );
}

function DeleteProjectModal({
  project,
  onClose,
  onDeleted,
}: {
  project: WorkspaceProjectInfo;
  onClose: () => void;
  onDeleted: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const projectName = project.display_name || project.name;
  const confirmPhrase = `delete ${projectName}`;
  const isConfirmed =
    confirmText.trim().toLowerCase() === confirmPhrase.toLowerCase();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const deleteProject = async () => {
    if (!isConfirmed) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      await deleteWorkspaceProject(project.id);
      toast(`${projectName} has been deleted`, "success");
      await onDeleted();
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mx-4 w-full max-w-md overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-[var(--color-error)]/20 bg-[var(--color-error)]/5 px-5 py-4">
          <div className="rounded-full bg-[var(--color-error)]/10 p-2">
            <AlertTriangle className="h-5 w-5 text-[var(--color-error)]" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-[var(--color-text)]">
              Delete Project
            </h3>
            <p className="text-xs text-[var(--color-text-dim)]">
              This action cannot be undone
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className={ICON_BUTTON}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="text-sm text-[var(--color-text-dim)]">
            This will permanently delete{" "}
            <span className="font-semibold text-[var(--color-text)]">
              {projectName}
            </span>
            , including all branches, files, and commit history.
          </div>

          <label className="block space-y-2">
            <span className="block text-xs font-medium text-[var(--color-text-dim)]">
              To confirm, type{" "}
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[var(--color-text)]">
                {confirmPhrase}
              </span>
            </span>
            <input
              ref={inputRef}
              type="text"
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && isConfirmed) {
                  void deleteProject();
                }
              }}
              placeholder={confirmPhrase}
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2 font-mono text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-text-dim)]"
              autoComplete="off"
              spellCheck={false}
            />
          </label>

          {error && (
            <div className="rounded-md border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 px-3 py-2 text-xs text-[var(--color-error)]">
              {error}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-[var(--color-border)] bg-muted/30 px-5 py-3">
          <button type="button" className={OUTLINE_BUTTON} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="inline-flex items-center justify-center gap-2 border border-[var(--color-error)] px-4 py-2 text-xs uppercase tracking-wider text-[var(--color-error)] transition-all hover:bg-[var(--color-error)]/10 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void deleteProject()}
            disabled={!isConfirmed || deleting}
          >
            {deleting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            Delete project
          </button>
        </div>
      </div>
    </div>
  );
}

export function NotionConversationList({
  conversations,
  loading,
  error,
  onOpen,
}: {
  conversations: NotionConversation[];
  loading: boolean;
  error: string | null;
  onOpen: (href: string) => void;
}) {
  if (loading && conversations.length === 0) {
    return (
      <div className="flex items-center justify-center gap-3 border border-[var(--color-border)] px-5 py-10 text-xs uppercase tracking-wider text-[var(--color-text-dim)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        loading notion requests...
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-[var(--color-error)]/40 px-5 py-4 text-xs text-[var(--color-error)]">
        Could not load Notion requests: {error}
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-[var(--color-text-dim)]">
        <NotionIcon className="mx-auto mb-2 h-6 w-6 opacity-40" />
        <p>No Notion requests found.</p>
        <p className="mt-1 text-xs">@ SignalPilot in your Notion workspace.</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-[var(--color-border)] border border-[var(--color-border)]">
      {conversations.map((conversation) => {
        const file = conversation.notebook_path || "";
        const params = new URLSearchParams();
        if (file) {
          params.set("file", file);
        }
        params.set("session_id", conversation.id);
        const href = `/projects?${params.toString()}`;
        const status = conversation.status || "saved";
        return (
          <a
            key={conversation.id}
            href={href}
            onClick={(event) => {
              event.preventDefault();
              onOpen(href);
            }}
            className="flex items-center gap-4 px-5 py-4 transition-colors hover:bg-[var(--color-bg-hover)]"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-[var(--color-text)]">
                {conversation.title || "Notion request"}
              </div>
              <div className="mt-1 truncate font-mono text-[11px] text-[var(--color-text-dim)]">
                {file || conversation.id}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="border border-[var(--color-border)] px-2 py-1 text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
                {status}
              </span>
              <span className="text-[11px] text-[var(--color-text-dim)]">
                {formatConversationTime(conversation.updated_at)}
              </span>
              <ExternalLink className="h-4 w-4 text-[var(--color-text-dim)]" />
            </div>
          </a>
        );
      })}
    </div>
  );
}
