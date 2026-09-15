"use client";

import { BookOpen, Database, ExternalLink, Loader2, Trash2, X } from "lucide-react";
import type { NotionOAuthInstallation } from "~/lib/api";
import type { WorkspaceProjectInfo } from "~/lib/types";
import { StatusDot } from "~/components/ui/data-viz";
import { notionPageUrl, oauthStatus, projectLabel, shortenedId } from "../_lib/helpers";

interface NotionInstallationCardProps {
  installation: NotionOAuthInstallation;
  /** Member view: values only, no disconnect or provisioning controls. */
  readOnly?: boolean;
  workspaceProjects: WorkspaceProjectInfo[];
  projectsById: Map<string, WorkspaceProjectInfo>;
  selection: string | undefined;
  onSelectProject: (projectId: string) => void;
  provisioning: boolean;
  deleting: boolean;
  onRequestDelete: () => void;
  onCancelDelete: () => void;
  onDelete: () => void;
  onProvision: () => void;
}

export function NotionInstallationCard({
  installation,
  readOnly = false,
  workspaceProjects,
  projectsById,
  selection,
  onSelectProject,
  provisioning,
  deleting,
  onRequestDelete,
  onCancelDelete,
  onDelete,
  onProvision,
}: NotionInstallationCardProps) {
  const status = oauthStatus(installation);
  const parentUrl = notionPageUrl(installation.config?.parent_page_id);
  const triggerUrl = notionPageUrl(installation.config?.trigger_page_id);
  const requestsUrl = notionPageUrl(installation.config?.requests_database_page_id);
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5 mb-3">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <BookOpen className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
            <span className="text-[13px] text-[var(--color-text)] font-medium">
              {installation.workspace_name || installation.workspace_id}
            </span>
            <StatusDot status={status.tone} size={4} />
            <span className="text-[10px] text-[var(--color-text-dim)] tracking-wider uppercase">{status.label}</span>
          </div>
          <div className="space-y-1 text-[11px] text-[var(--color-text-dim)]">
            <p className="flex items-center gap-1.5">
              <span>
                integration page:
                {!installation.config?.parent_page_id && (
                  <span className="ml-1 text-[var(--color-error)]">*</span>
                )}
              </span>
              <span className="text-[var(--color-text-muted)] font-mono">{shortenedId(installation.config?.parent_page_id)}</span>
              {parentUrl && (
                <a href={parentUrl} target="_blank" rel="noopener noreferrer" title="open integration page in Notion" aria-label="open integration page in Notion" className="inline-flex h-4 w-4 items-center justify-center text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </p>
            <p className="flex items-center gap-1.5">
              <span>trigger page:</span>
              <span className="text-[var(--color-text-muted)] font-mono">{shortenedId(installation.config?.trigger_page_id)}</span>
              {triggerUrl && (
                <a href={triggerUrl} target="_blank" rel="noopener noreferrer" title="open trigger page in Notion" aria-label="open trigger page in Notion" className="inline-flex h-4 w-4 items-center justify-center text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </p>
            <p className="flex items-center gap-1.5">
              <span>requests database:</span>
              <span className="text-[var(--color-text-muted)] font-mono">{shortenedId(installation.config?.requests_database_page_id)}</span>
              {requestsUrl && (
                <a href={requestsUrl} target="_blank" rel="noopener noreferrer" title="open requests database in Notion" aria-label="open requests database in Notion" className="inline-flex h-4 w-4 items-center justify-center text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
                  <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </p>
            <p className="flex items-center gap-1.5">
              <span>
                default project:
                {!installation.config?.default_project_id && (
                  <span className="ml-1 text-[var(--color-error)]">*</span>
                )}
              </span>
              <span className="text-[var(--color-text-muted)] font-mono truncate">
                {(() => {
                  const project = installation.config?.default_project_id
                    ? projectsById.get(installation.config.default_project_id)
                    : null;
                  return project
                    ? projectLabel(project)
                    : shortenedId(installation.config?.default_project_id);
                })()}
              </span>
            </p>
          </div>
        </div>

        {readOnly ? null : deleting ? (
          <div className="flex items-center gap-1.5">
            <button onClick={() => onDelete()} className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/30 rounded-[10px] hover:border-[var(--color-error)] transition-colors duration-150">confirm</button>
            <button onClick={() => onCancelDelete()} className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"><X className="w-3 h-3" /></button>
          </div>
        ) : (
          <button
            onClick={() => onRequestDelete()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-error)]/50 hover:text-[var(--color-error)] transition-colors duration-150"
          >
            <Trash2 className="w-3 h-3" />
            disconnect
          </button>
        )}
      </div>

      {readOnly ? null : (() => {
        const configuredProjectId = installation.config?.default_project_id || "";
        const selectedProjectId = selection ?? configuredProjectId;
        const selectedProject = selectedProjectId ? projectsById.get(selectedProjectId) : null;
        const projectChanged = selectedProjectId !== configuredProjectId;
        const configuredParentPageId = installation.config?.parent_page_id || "";
        const canSubmitProject =
          Boolean(selectedProject) &&
          !provisioning &&
          (!installation.config?.enabled || projectChanged || !configuredParentPageId);

        return (
          <div className="border-t border-[var(--color-border)] pt-4 space-y-3">
            <div>
              <label htmlFor={`notion-project-${installation.id}`} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">
                default project
                <span className="ml-1 text-[var(--color-error)]">*</span>
              </label>
              <div className="flex flex-col sm:flex-row gap-2">
                <select
                  id={`notion-project-${installation.id}`}
                  value={selectedProjectId}
                  onChange={(event) => onSelectProject(event.target.value)}
                  disabled={workspaceProjects.length === 0 || provisioning}
                  className="min-w-0 flex-1 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none disabled:opacity-40"
                >
                  <option value="">
                    {workspaceProjects.length === 0 && !selectedProjectId ? "no active projects" : "select a project..."}
                  </option>
                  {selectedProjectId && !selectedProject && (
                    <option value={selectedProjectId}>configured project unavailable</option>
                  )}
                  {workspaceProjects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {projectLabel(project)}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => onProvision()}
                  disabled={!canSubmitProject}
                  className="flex items-center justify-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] rounded-[10px] transition-opacity duration-150 hover:opacity-90 disabled:opacity-30"
                >
                  {provisioning ? <Loader2 className="w-3 h-3 animate-spin" /> : <Database className="w-3 h-3" />}
                  {installation.config?.enabled ? "save setup" : "provision integration"}
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
