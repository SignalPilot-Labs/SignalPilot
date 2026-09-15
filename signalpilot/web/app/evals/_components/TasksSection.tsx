"use client";

/** Task gallery: search, filters, card/list views, and paging over the eval set. */

import { useEffect, useMemo, useState } from "react";
import { BookOpen, ChevronRight, LayoutGrid, List, Search, X } from "lucide-react";
import { type EvalTask } from "~/lib/api";
import { fmtNum } from "./Markdown";
import { ClassBadge } from "./badges";

export function docTitle(t: EvalTask): string {
  const m = t.doc.match(/^#\s+(.+)$/m);
  return m ? m[1] : t.title;
}

function isControl(t: EvalTask): boolean {
  return t.kind === "control" || /control/i.test(t.why + t.doc.slice(0, 200));
}

function TaskCard({ t, onOpen }: { t: EvalTask; onOpen: () => void }) {
  const rebuild = t.grade?.kind === "model_rebuilt";
  return (
    <button className="ev-qcard" onClick={onOpen}>
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm text-[var(--color-text)] leading-snug">{docTitle(t)}</span>
        <ChevronRight className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[var(--color-text-dim)]" />
      </div>
      <p className="mt-1 text-[11px] font-mono text-[var(--color-text-dim)]">{t.id}</p>
      <div className="mt-3 flex items-center gap-1.5 flex-wrap">
        <ClassBadge cls={t.class} />
        <span className={`ev-badge ${isControl(t) ? "ev-badge--control" : ""}`}>{isControl(t) ? "control" : t.kind}</span>
        {rebuild && <span className="ev-badge">rebuild</span>}
        {t.doc && <span className="ev-badge"><BookOpen className="w-2.5 h-2.5" />docs</span>}
      </div>
      <div className="mt-2.5 flex gap-1.5 flex-wrap">
        {t.checks.map((c) => (
          <span key={c.name} className="ev-chip">
            <span className="n">{c.name}</span>
            {fmtNum(c.value)}
            <span className="n">±{Math.round(c.tolerance * 100)}%</span>
          </span>
        ))}
        {t.builds.length > 0 && (
          <span className="ev-chip"><span className="n">builds</span>{t.builds.length}</span>
        )}
      </div>
    </button>
  );
}

function TaskRow({ t, onOpen }: { t: EvalTask; onOpen: () => void }) {
  return (
    <button className="ev-qrow" onClick={onOpen}>
      <span className="ev-qrow-id">{t.id}</span>
      <span className="ev-qrow-title">{docTitle(t)}</span>
      <span className="ev-qrow-badges">
        <ClassBadge cls={t.class} />
        <span className={`ev-badge ${isControl(t) ? "ev-badge--control" : ""}`}>{isControl(t) ? "control" : t.kind}</span>
        {t.doc && <span className="ev-badge"><BookOpen className="w-2.5 h-2.5" />docs</span>}
      </span>
      <span className="ev-qrow-checks">
        {t.grade?.kind === "model_rebuilt"
          ? "rebuild"
          : t.checks.length
            ? `${t.checks.length} check${t.checks.length === 1 ? "" : "s"}`
            : "ungraded"}
      </span>
      <ChevronRight className="w-3.5 h-3.5 flex-shrink-0 text-[var(--color-text-dim)]" />
    </button>
  );
}

const TASK_PAGE = 60;

export function TasksSection({ tasks, onOpen }: { tasks: EvalTask[]; onOpen: (t: EvalTask) => void }) {
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<string | null>(null);
  const [classFilter, setClassFilter] = useState<string | null>(null);
  // Use the card view for small task sets.
  // Use the list view when the set contains more than 100 tasks.
  // The user can override the default view.
  const [view, setView] = useState<"cards" | "list">(tasks.length > 24 ? "list" : "cards");
  const [limit, setLimit] = useState(TASK_PAGE);

  const kinds = useMemo(() => {
    const m = new Map<string, number>();
    tasks.forEach((t) => m.set(t.kind, (m.get(t.kind) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [tasks]);

  const classes = useMemo(() => {
    const m = new Map<string, number>();
    tasks.forEach((t) => m.set(t.class, (m.get(t.class) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [tasks]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return tasks.filter((t) => {
      if (kindFilter && t.kind !== kindFilter) return false;
      if (classFilter && t.class !== classFilter) return false;
      if (!needle) return true;
      return (
        t.id.toLowerCase().includes(needle) ||
        t.title.toLowerCase().includes(needle) ||
        docTitle(t).toLowerCase().includes(needle) ||
        t.prompt.toLowerCase().includes(needle) ||
        t.why.toLowerCase().includes(needle) ||
        t.builds.some((b) => b.toLowerCase().includes(needle)) ||
        t.covers.some((c) => c.toLowerCase().includes(needle))
      );
    });
  }, [tasks, query, kindFilter, classFilter]);

  // Reset paging whenever the visible set changes.
  useEffect(() => setLimit(TASK_PAGE), [query, kindFilter, classFilter, view]);

  const visible = filtered.slice(0, limit);
  const showFilters = tasks.length > 6;

  return (
    <div>
      {showFilters && (
        <div className="ev-toolbar">
          <div className="ev-search">
            <Search className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${tasks.length} tasks…`}
              aria-label="search tasks"
            />
            {query && (
              <button onClick={() => setQuery("")} aria-label="clear search" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
          {classes.length > 1 && (
            <div className="ev-filter-group">
              {classes.map(([c, n]) => (
                <button
                  key={c}
                  className={`ev-filter ${classFilter === c ? "ev-filter--on" : ""}`}
                  onClick={() => setClassFilter(classFilter === c ? null : c)}
                >
                  {c} <span className="n">{n}</span>
                </button>
              ))}
            </div>
          )}
          {kinds.length > 1 && (
            <div className="ev-filter-group">
              {kinds.map(([k, n]) => (
                <button
                  key={k}
                  className={`ev-filter ${kindFilter === k ? "ev-filter--on" : ""}`}
                  onClick={() => setKindFilter(kindFilter === k ? null : k)}
                >
                  {k} <span className="n">{n}</span>
                </button>
              ))}
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums whitespace-nowrap">
              {filtered.length === tasks.length ? `${tasks.length}` : `${filtered.length} of ${tasks.length}`}
            </span>
            <div className="ev-view-toggle" role="group" aria-label="view mode">
              <button className={view === "list" ? "on" : ""} onClick={() => setView("list")} title="List view" aria-label="list view">
                <List className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
              <button className={view === "cards" ? "on" : ""} onClick={() => setView("cards")} title="Card view" aria-label="card view">
                <LayoutGrid className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
            </div>
          </div>
        </div>
      )}

      {filtered.length === 0 ? (
        <p className="mt-4 text-sm text-[var(--color-text-dim)]">no tasks match — clear the search or filters</p>
      ) : view === "cards" ? (
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
          {visible.map((t) => (
            <TaskCard key={t.id} t={t} onOpen={() => onOpen(t)} />
          ))}
        </div>
      ) : (
        <div className="mt-3 ev-card divide-y divide-[var(--color-border)]">
          {visible.map((t) => (
            <TaskRow key={t.id} t={t} onOpen={() => onOpen(t)} />
          ))}
        </div>
      )}

      {filtered.length > limit && (
        <div className="mt-3 flex justify-center">
          <button
            onClick={() => setLimit(limit + TASK_PAGE)}
            className="px-4 py-1.5 rounded-[10px] text-xs border border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors"
          >
            Show {Math.min(TASK_PAGE, filtered.length - limit)} more · {filtered.length - limit} remaining
          </button>
        </div>
      )}
    </div>
  );
}
