"use client";

import type { ReactNode } from "react";
import type { KnowledgeDoc } from "~/lib/types";
import { CATEGORY_META } from "./categories";
import { snippet, daysAgo, scopeLabel } from "./shared";
import { KbIcon } from "./icons";

export type SortKey = "views" | "recent" | "alpha" | "least";
const SORT_LABEL: Record<SortKey, string> = {
  views: "Most pulled",
  recent: "Recent",
  alpha: "A–Z",
  least: "Least pulled",
};

export function DocList({
  icon,
  title,
  countLabel,
  subtitle,
  showControls = true,
  list,
  sortBy,
  onCycleSort,
  filters,
  onToggleFilter,
  selectedId,
  onSelect,
  showScope = false,
}: {
  icon: ReactNode;
  title: string;
  countLabel: string;
  subtitle?: string;
  showControls?: boolean;
  list: KnowledgeDoc[];
  sortBy: SortKey;
  onCycleSort: () => void;
  filters: Set<string>;
  onToggleFilter: (f: string) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  showScope?: boolean;
}) {
  return (
    <div className="kb-list">
      <div className={`kb-list-bar${!showControls ? " review" : ""}`}>
        <div className="r1">
          <div className="kb-list-title">
            {icon}
            <span className="tx">{title}</span>
            <span className="c">{countLabel}</span>
          </div>
          {showControls && (
            <button className="kb-sortbtn" onClick={onCycleSort}>
              <KbIcon name="sortArrows" />
              {SORT_LABEL[sortBy]}
            </button>
          )}
        </div>
        {subtitle && <div className="kb-list-subtitle">{subtitle}</div>}
        {showControls && (
          <div className="kb-list-chips">
            <button className={`chip${filters.has("agent") ? " on" : ""}`} onClick={() => onToggleFilter("agent")}>
              <KbIcon name="cpu" />
              Agent-written
            </button>
            <button className={`chip${filters.has("unused") ? " on" : ""}`} onClick={() => onToggleFilter("unused")}>
              <KbIcon name="slash" />
              Never pulled
            </button>
          </div>
        )}
      </div>

      <div className="kb-rows">
        {list.length === 0 ? (
          <div className="kb-list-empty">No documents match.</div>
        ) : (
          list.map((d) => {
            const sn = snippet(d);
            return (
              <button
                key={d.id}
                className={`kb-row${selectedId === d.id ? " sel" : ""}`}
                onClick={() => onSelect(d.id)}
              >
                <div className="mid">
                  <div className="tt">
                    {showScope && (
                      <span className="catdot" style={{ background: CATEGORY_META[d.category].color }} title={d.category} />
                    )}
                    {d.status === "pending" && <span className="kb-pend-dot" title="pending" />}
                    <span className="tt-text">{d.title}</span>
                  </div>
                  <div className="sn">{sn || "— no content —"}</div>
                </div>
                <div className="rt">
                  <span className="v" title="times pulled into agent context via MCP">
                    {d.view_count > 0 ? (
                      <><KbIcon name="pull" size={12} />{d.view_count}</>
                    ) : (
                      <span className="dim">never pulled</span>
                    )}
                  </span>
                  <div className="m">
                    <span className="sc">{scopeLabel(d)}</span>
                    <span>{daysAgo(d.updated_at)}</span>
                    <KbIcon name={d.proposed_by_agent ? "cpu" : "user"} size={12} />
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
