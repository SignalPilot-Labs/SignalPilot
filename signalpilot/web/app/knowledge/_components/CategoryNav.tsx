"use client";

import type { KnowledgeDoc } from "~/lib/types";
import { BROWSE_CATEGORIES, GOD_DOC_CATEGORY, CATEGORY_META } from "./categories";
import { CatBox } from "./shared";
import { KbIcon } from "./icons";

export type ScopeFilter = "all" | "org" | "project" | "connection";
const SCOPES: { key: ScopeFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "org", label: "Org" },
  { key: "project", label: "Project" },
  { key: "connection", label: "Conn" },
];

export type NavState =
  | { kind: "category"; cat: KnowledgeDoc["category"] }
  | { kind: "pending" }
  | { kind: "archived" };

export function CategoryNav({
  docs,
  pendingCount,
  archivedCount,
  nav,
  search,
  onSearch,
  onCategory,
  onManage,
  scopeFilter,
  onScopeFilter,
}: {
  docs: KnowledgeDoc[];
  pendingCount: number;
  archivedCount: number;
  nav: NavState;
  search: string;
  onSearch: (q: string) => void;
  onCategory: (cat: KnowledgeDoc["category"]) => void;
  onManage: (kind: "pending" | "archived") => void;
  scopeFilter: ScopeFilter;
  onScopeFilter: (s: ScopeFilter) => void;
}) {
  const inScope = (d: KnowledgeDoc) => scopeFilter === "all" || d.scope === scopeFilter;
  const countOf = (c: KnowledgeDoc["category"]) => docs.filter((d) => inScope(d) && d.category === c).length;
  const isCat = (c: KnowledgeDoc["category"]) => nav.kind === "category" && nav.cat === c && !search;

  const godMeta = CATEGORY_META[GOD_DOC_CATEGORY];

  return (
    <nav className="kb-nav">
      <div className="kb-search kb-nav-search">
        <KbIcon name="search" size={15} />
        <input value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Search knowledge…" />
        {search && (
          <button className="kb-search-clear" onClick={() => onSearch("")} aria-label="clear search">
            <KbIcon name="close" size={13} />
          </button>
        )}
      </div>

      <div className="kb-scopebar">
        {SCOPES.map((s) => (
          <button key={s.key} className={scopeFilter === s.key ? "sel" : ""} onClick={() => onScopeFilter(s.key)}>
            {s.label}
          </button>
        ))}
      </div>

      <div className="kb-nav-label first">Always loaded</div>
      <button
        className={`kb-nav-item kb-nav-god${isCat(GOD_DOC_CATEGORY) ? " sel" : ""}`}
        onClick={() => onCategory(GOD_DOC_CATEGORY)}
        title={godMeta.description}
      >
        <CatBox category={GOD_DOC_CATEGORY} />
        <span className="nm">{godMeta.label}</span>
        <span className="cnt">{countOf(GOD_DOC_CATEGORY)}</span>
      </button>

      <div className="kb-nav-label">Categories</div>
      {BROWSE_CATEGORIES.map((c) => {
        const n = countOf(c);
        const meta = CATEGORY_META[c];
        return (
          <button key={c} className={`kb-nav-item${isCat(c) ? " sel" : ""}`} onClick={() => onCategory(c)} title={meta.description}>
            <CatBox category={c} />
            <span className="nm">{meta.label}</span>
            <span className="cnt">{n}</span>
          </button>
        );
      })}

      <div className="kb-nav-label">Manage</div>
      <button
        className={`kb-nav-item${pendingCount > 0 ? " warn" : ""}${nav.kind === "pending" ? " sel" : ""}`}
        onClick={() => onManage("pending")}
      >
        <span className="rico"><KbIcon name="clock" /></span>
        <span className="nm" style={{ textTransform: "none" }}>Pending review</span>
        <span className="cnt">{pendingCount}</span>
      </button>
      <button className={`kb-nav-item${nav.kind === "archived" ? " sel" : ""}`} onClick={() => onManage("archived")}>
        <span className="rico"><KbIcon name="archive" /></span>
        <span className="nm" style={{ textTransform: "none" }}>Archived</span>
        <span className="cnt">{archivedCount}</span>
      </button>
    </nav>
  );
}
