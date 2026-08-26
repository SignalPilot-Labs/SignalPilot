"use client";

import type { KnowledgeDoc } from "~/lib/types";
import { CATEGORY_ORDER } from "./categories";
import { CatBox, snippet, daysAgo } from "./shared";
import { KbIcon } from "./icons";

function QuickCard({ doc, onSelect }: { doc: KnowledgeDoc; onSelect: (id: string) => void }) {
  return (
    <button type="button" className="kb-qcard" onClick={() => onSelect(doc.id)}>
      <div className="kb-qcard-top">
        <CatBox category={doc.category} size={28} iconSize={16} />
        <span className="kb-qcard-cat">{doc.category}</span>
      </div>
      <div className="kb-qcard-title">{doc.title}</div>
      <div className="kb-qcard-snip">{snippet(doc)}</div>
      <div className="kb-qcard-foot">
        <span><b>{doc.view_count}</b> pulls</span>
        <span>{daysAgo(doc.updated_at)}</span>
      </div>
    </button>
  );
}

function Shelf({
  icon, label, docs, onSelect,
}: {
  icon: string; label: string; docs: KnowledgeDoc[]; onSelect: (id: string) => void;
}) {
  if (docs.length === 0) return null;
  return (
    <div className="kb-shelf">
      <div className="kb-shelf-h"><KbIcon name={icon} size={14} />{label}</div>
      <div className="kb-shelf-row">
        {docs.map((d) => <QuickCard key={d.id} doc={d} onSelect={onSelect} />)}
      </div>
    </div>
  );
}

export function QuickPick({
  docs,
  pending,
  onSelect,
  onSelectCategory,
}: {
  docs: KnowledgeDoc[];
  pending: KnowledgeDoc[];
  onSelect: (id: string) => void;
  onSelectCategory: (cat: KnowledgeDoc["category"]) => void;
}) {
  const active = docs.filter((d) => d.status === "active");
  const mostViewed = [...active].sort((a, b) => b.view_count - a.view_count).filter((d) => d.view_count > 0).slice(0, 10);
  const recent = [...active].sort((a, b) => b.updated_at - a.updated_at).slice(0, 10);
  const review = pending.slice(0, 10);
  const cats = CATEGORY_ORDER.map((c) => ({ c, n: active.filter((d) => d.category === c).length })).filter((x) => x.n > 0);

  if (active.length === 0 && review.length === 0) {
    return (
      <div className="kb-landing">
        <div className="kb-landing-empty">
          <KbIcon name="doc" size={28} style={{ color: "var(--color-text-dim)" }} />
          <div>No documents yet — create one to get started.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="kb-landing">
      <div className="kb-landing-head">Knowledge base</div>
      <div className="kb-landing-sub">
        {active.length} {active.length === 1 ? "document" : "documents"} — jump to a category or pick up where your agents left off.
      </div>
      <div className="kb-pills">
        {cats.map(({ c, n }) => (
          <button key={c} className="kb-pill-cat" onClick={() => onSelectCategory(c)}>
            <CatBox category={c} size={26} iconSize={15} />
            <span className="nm">{c}</span>
            <span className="c">{n}</span>
          </button>
        ))}
      </div>
      <Shelf icon="pull" label="Most pulled" docs={mostViewed} onSelect={onSelect} />
      <Shelf icon="clock" label="Recently updated" docs={recent} onSelect={onSelect} />
      <Shelf icon="hourglass" label="Needs review" docs={review} onSelect={onSelect} />
    </div>
  );
}
