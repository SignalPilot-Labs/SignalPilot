"use client";

import { Check, ChevronDown, ExternalLink, FolderGit2, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { StandaloneChatProject } from "~/lib/api";
import { dashboardDialectLabel } from "~/lib/dashboard/dialect-label";

function ReadinessDot({ ready }: { ready: boolean }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
      style={{ background: ready ? "var(--color-success)" : "var(--color-warning)" }}
    />
  );
}

/** Searchable project combobox. Selecting an unready project shows its
 * readiness reason and a settings link instead of silently committing a
 * broken selection. */
export function ProjectPicker({
  projects,
  selectedId,
  onSelect,
}: {
  projects: StandaloneChatProject[];
  selectedId: string | null;
  onSelect: (projectId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [inspectId, setInspectId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const selected = projects.find((p) => p.id === selectedId) ?? null;
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? projects.filter(
          (p) =>
            p.display_name.toLowerCase().includes(q) ||
            (p.connection_name ?? "").toLowerCase().includes(q),
        )
      : projects;
    return [...list].sort((a, b) => Number(b.ready) - Number(a.ready));
  }, [projects, query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setInspectId(null);
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="Select project"
        className="flex max-w-full items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1.5 text-xs text-[var(--color-text)] hover:border-[var(--color-border-hover)]"
      >
        <FolderGit2 className="h-3 w-3 shrink-0 text-[var(--color-text-dim)]" />
        {selected ? (
          <>
            <ReadinessDot ready={selected.ready} />
            <span className="truncate font-medium">{selected.display_name}</span>
            {selected.connection_name && (
              <span className="hidden truncate text-[var(--color-text-dim)] sm:inline">
                · {selected.connection_name}
              </span>
            )}
          </>
        ) : (
          <span className="text-[var(--color-text-dim)]">choose a project…</span>
        )}
        <ChevronDown className="h-3 w-3 shrink-0 text-[var(--color-text-dim)]" />
      </button>

      {open && (
        <div className="absolute bottom-10 left-0 z-30 w-[22rem] overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-xl">
          <div className="relative border-b border-[var(--color-border)]">
            <Search className="absolute left-3 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--color-text-dim)]" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="search projects…"
              className="w-full bg-transparent py-2 pl-8 pr-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:outline-none"
            />
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {filtered.length === 0 && (
              <p className="px-3 py-3 text-center text-[11px] text-[var(--color-text-dim)]">
                no projects match
              </p>
            )}
            {filtered.map((project) => (
              <div key={project.id}>
                <button
                  type="button"
                  onClick={() => {
                    if (project.ready) {
                      onSelect(project.id);
                      setOpen(false);
                      setInspectId(null);
                    } else {
                      setInspectId((prev) => (prev === project.id ? null : project.id));
                    }
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[var(--color-bg-hover)]"
                >
                  <ReadinessDot ready={project.ready} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs text-[var(--color-text)]">
                      {project.display_name}
                    </span>
                    <span className="block truncate text-[10px] text-[var(--color-text-dim)]">
                      {[
                        project.connection_type
                          ? dashboardDialectLabel(project.connection_type)
                          : null,
                        project.connection_name,
                        project.default_branch,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "no connection"}
                    </span>
                  </span>
                  {project.id === selectedId && (
                    <Check className="h-3 w-3 shrink-0 text-[var(--color-success)]" />
                  )}
                </button>
                {inspectId === project.id && (
                  <div className="mx-3 mb-2 rounded-lg border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 px-3 py-2">
                    <p className="text-[11px] leading-4 text-[var(--color-warning)]">
                      {project.readiness_message || "This project is not ready for chat."}
                    </p>
                    <a
                      href={`/projects/${project.id}/settings`}
                      className="mt-1 inline-flex items-center gap-1 text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                    >
                      fix in project settings <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Persistent chip once a conversation is welded to its project. */
export function ProjectChip({
  project,
  commitSha,
}: {
  project: StandaloneChatProject | null;
  commitSha?: string | null;
}) {
  if (!project) return null;
  return (
    <span
      className="flex max-w-full items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1.5 text-xs text-[var(--color-text-muted)]"
      title={[
        `project: ${project.display_name}`,
        project.connection_name ? `connection: ${project.connection_name}` : null,
        project.connection_type
          ? `database: ${dashboardDialectLabel(project.connection_type)}`
          : null,
        `branch: ${project.default_branch}`,
        commitSha ? `commit: ${commitSha.slice(0, 12)}` : null,
        project.ready ? "ready" : project.readiness_message,
      ]
        .filter(Boolean)
        .join("\n")}
    >
      <FolderGit2 className="h-3 w-3 shrink-0 text-[var(--color-text-dim)]" />
      <ReadinessDot ready={project.ready} />
      <span className="truncate">{project.display_name}</span>
      {project.connection_name && (
        <span className="hidden truncate text-[var(--color-text-dim)] sm:inline">
          · {project.connection_name}
        </span>
      )}
    </span>
  );
}
