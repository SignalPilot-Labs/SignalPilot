"use client";

import { useState, useEffect, useCallback, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Plus, RefreshCw, Loader2 } from "lucide-react";
import {
  updateKnowledgeDoc,
  archiveKnowledgeDoc,
  approveKnowledgeDoc,
  getKnowledgeDoc,
} from "~/lib/api";
import {
  useKnowledgeDocs,
  useKnowledgeEdits,
  invalidateKnowledge,
  SWR_KEYS,
} from "~/lib/hooks/use-gateway-data";
import type { KnowledgeDoc, KnowledgeEdit } from "~/lib/types";
import { useToast } from "~/components/ui/toast";
import { PageLoader } from "~/components/ui/page-loader";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";

import "./knowledge.css";
import { CategoryNav, type NavState, type ScopeFilter } from "./_components/CategoryNav";
import { DocList, type SortKey } from "./_components/DocList";
import { QuickPick } from "./_components/QuickPick";
import { DocumentView, resolveWikilink } from "./_components/DocumentView";
import { CreateDocForm } from "./_components/CreateDocForm";
import { HistoryModal } from "./_components/HistoryModal";
import { CatBox, docPath } from "./_components/shared";
import { KbIcon } from "./_components/icons";
import { CATEGORY_ORDER, CATEGORY_META } from "./_components/categories";

const SORT_CYCLE: SortKey[] = ["views", "recent", "alpha", "least"];

function KnowledgePage() {
  const { toast } = useToast();
  const searchParams = useSearchParams();

  // ── UI state ──
  const [nav, setNav] = useState<NavState>({ kind: "category", cat: "decisions" });
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get("entry"));
  const [editMode, setEditMode] = useState(false);
  const [editBuffer, setEditBuffer] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");
  const [sortBy, setSortBy] = useState<SortKey>("views");
  const [filters, setFilters] = useState<Set<string>>(new Set());
  const [historyOpen, setHistoryOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [dirtyConfirm, setDirtyConfirm] = useState(false);
  const [pendingSelectId, setPendingSelectId] = useState<string | null>(null);

  // ── data ──
  const { data: docs, isLoading, mutate: refreshList } = useKnowledgeDocs({ status: "active" });
  const { data: pending, mutate: refreshPending } = useKnowledgeDocs({ status: "pending" });
  const { data: archivedDocs, mutate: refreshArchived } = useKnowledgeDocs({ status: "archived" });
  const { data: selectedDoc, mutate: refreshDoc } = useSWR<KnowledgeDoc>(
    selectedId ? SWR_KEYS.knowledgeDoc(selectedId) : null,
    () => getKnowledgeDoc(selectedId!),
    {
      dedupingInterval: 30_000,
      onError: (err) => {
        const msg = err instanceof Error ? err.message : "";
        if (msg.startsWith("404")) {
          setSelectedId(null);
          toast("doc not found — may have been archived", "error");
        }
      },
    },
  );
  const { data: edits, mutate: refreshEdits } = useKnowledgeEdits(historyOpen ? selectedId : null);

  const active = docs ?? [];
  const pendingDocs = pending ?? [];
  const archived = archivedDocs ?? [];
  const pendingCount = pendingDocs.length;

  // Default the nav to the largest non-empty category once docs load.
  const inited = useRef(false);
  useEffect(() => {
    if (inited.current || active.length === 0) return;
    inited.current = true;
    if (nav.kind === "category" && active.filter((d) => d.category === nav.cat).length === 0) {
      const best = [...CATEGORY_ORDER]
        .map((c) => ({ c, n: active.filter((d) => d.category === c).length }))
        .sort((a, b) => b.n - a.n)[0];
      if (best && best.n > 0) setNav({ kind: "category", cat: best.c });
    }
  }, [active, nav]);

  // editBuffer sync
  useEffect(() => {
    if (editMode && selectedDoc) setEditBuffer(selectedDoc.body ?? "");
  }, [editMode, selectedDoc?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ⌘E to edit
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if ((e.metaKey || e.ctrlKey) && e.key === "e" && selectedId && !editMode) {
        e.preventDefault();
        setEditMode(true);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [selectedId, editMode]);

  function syncEntry(id: string | null) {
    if (typeof window === "undefined") return;
    window.history.replaceState(null, "", id ? `/knowledge?entry=${id}` : "/knowledge");
  }

  // ── backlinks ──
  function backlinksFor(id: string): KnowledgeDoc[] {
    const re = /\[\[([^\]\n]+)\]\]/g;
    const out: KnowledgeDoc[] = [];
    for (const src of active) {
      if (!src.body || src.id === id) continue;
      re.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = re.exec(src.body)) !== null) {
        const t = resolveWikilink(m[1], active);
        if (t && t.id === id) { out.push(src); break; }
      }
    }
    return out;
  }

  // ── navigation ──
  // Switching the nav only changes the menu/list — it keeps the currently open
  // document in the reader so you can browse without losing your place.
  function selectCategory(cat: KnowledgeDoc["category"]) {
    setNav({ kind: "category", cat });
    setSearchQ(""); setFilters(new Set());
  }
  function selectManage(kind: "pending" | "archived") {
    setNav({ kind } as NavState);
    setSearchQ(""); setFilters(new Set());
  }
  function handleSelectDoc(id: string) {
    if (editMode && editBuffer !== (selectedDoc?.body ?? "")) {
      setPendingSelectId(id); setDirtyConfirm(true); return;
    }
    setEditMode(false); setSelectedId(id); syncEntry(id);
  }
  function toggleFilter(f: string) {
    setFilters((prev) => { const n = new Set(prev); n.has(f) ? n.delete(f) : n.add(f); return n; });
  }
  function cycleSort() { setSortBy((s) => SORT_CYCLE[(SORT_CYCLE.indexOf(s) + 1) % SORT_CYCLE.length]); }

  // ── mutations ──
  async function handleSave() {
    if (!selectedId) return;
    setSaving(true);
    try {
      await updateKnowledgeDoc(selectedId, editBuffer);
      toast("saved", "success");
      setEditMode(false);
      await Promise.all([refreshDoc(), refreshList(), invalidateKnowledge()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      toast(msg.includes("403") ? "admin scope required" : `save failed: ${msg}`, "error");
    } finally { setSaving(false); }
  }
  async function handleArchive() {
    if (!selectedId) return;
    try {
      await archiveKnowledgeDoc(selectedId);
      toast("archived", "success");
      setSelectedId(null); setEditMode(false);
      await Promise.all([refreshList(), refreshPending(), refreshArchived(), invalidateKnowledge()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      toast(msg.includes("403") ? "admin scope required" : `archive failed: ${msg}`, "error");
    }
  }
  async function handleApprove(id: string) {
    try {
      await approveKnowledgeDoc(id);
      toast("approved", "success");
      if (id === selectedId) setSelectedId(null);
      await Promise.all([refreshList(), refreshPending(), invalidateKnowledge()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      toast(msg.includes("403") ? "admin scope required" : `approve failed: ${msg}`, "error");
    }
  }
  async function handleRevert(edit: KnowledgeEdit) {
    if (!selectedId) return;
    try {
      await updateKnowledgeDoc(selectedId, edit.body_before);
      toast("reverted", "success");
      setHistoryOpen(false);
      await Promise.all([refreshDoc(), refreshList(), invalidateKnowledge(), refreshEdits()]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      toast(msg.includes("403") ? "admin scope required" : `revert failed: ${msg}`, "error");
    }
  }
  const handleEditKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); handleSave(); }
      if (e.key === "Escape") {
        if (editBuffer !== (selectedDoc?.body ?? "")) setDirtyConfirm(true);
        else setEditMode(false);
      }
    },
    [editBuffer, selectedDoc?.body], // eslint-disable-line react-hooks/exhaustive-deps
  );

  // ── list set ──
  function passFilters(d: KnowledgeDoc) {
    if (filters.has("agent") && !d.proposed_by_agent) return false;
    if (filters.has("unused") && d.view_count > 0) return false;
    return true;
  }
  function sortDocs(a: KnowledgeDoc, b: KnowledgeDoc) {
    if (sortBy === "views") return b.view_count - a.view_count || a.title.localeCompare(b.title);
    if (sortBy === "recent") return b.updated_at - a.updated_at;
    if (sortBy === "alpha") return a.title.localeCompare(b.title);
    return a.view_count - b.view_count;
  }

  const isFirstLoad = isLoading && active.length === 0;
  if (isFirstLoad) return <PageLoader label="loading knowledge base" />;

  // current list + header
  let baseSet: KnowledgeDoc[] = [];
  let listIcon = <KbIcon name="search" size={17} style={{ color: "var(--color-text-dim)" }} />;
  let listTitle = "Search";
  let listCount = "";
  let listSubtitle: string | undefined;
  let listControls = true;
  let showScope = true;
  const scopedActive = scopeFilter === "all" ? active : active.filter((d) => d.scope === scopeFilter);
  if (searchQ) {
    const q = searchQ.toLowerCase();
    baseSet = scopedActive.filter((d) => (d.title + " " + (d.body ?? "")).toLowerCase().includes(q));
    listTitle = "Search"; listCount = `“${searchQ}” · ${baseSet.length}`;
  } else if (nav.kind === "pending") {
    baseSet = pendingDocs; listIcon = <KbIcon name="clock" size={17} style={{ color: "var(--color-warning)" }} />;
    listTitle = "Pending review"; listCount = `${baseSet.length} ${baseSet.length === 1 ? "doc" : "docs"}`;
    listControls = false;
    listSubtitle = baseSet.length
      ? "Agent-proposed documents awaiting your review. Open one to approve or deny it."
      : "Nothing to review — agent proposals will appear here for approval.";
  } else if (nav.kind === "archived") {
    baseSet = archived; listIcon = <KbIcon name="archive" size={17} style={{ color: "var(--color-text-dim)" }} />;
    listTitle = "Archived"; listCount = `${baseSet.length}`;
  } else if (nav.kind === "category") {
    baseSet = scopedActive.filter((d) => d.category === nav.cat);
    listIcon = <CatBox category={nav.cat} size={26} iconSize={15} />;
    listTitle = CATEGORY_META[nav.cat].label;
    listCount = `${baseSet.length} ${baseSet.length === 1 ? "doc" : "docs"}`;
    listSubtitle = CATEGORY_META[nav.cat].description;
    showScope = false;
  }
  const list = baseSet.filter(passFilters).sort(sortDocs);

  return (
    <div className="kb-root h-screen flex flex-col p-8 overflow-hidden animate-fade-in">
      {/* Header */}
      <div className="kb-header">
        <div className="kb-logo">
          <span className="kb-glyph"><KbIcon name="bookOpen" /></span>
          <span className="ti">Knowledge base</span>
        </div>
        <div className="kb-crumb"><b>org conventions</b><span className="sl">·</span>project decisions<span className="sl">·</span>connection quirks</div>
        <div className="flex-1" />
        <button onClick={() => setCreating(true)} className="kb-btn kb-btn-primary">
          <Plus className="w-3.5 h-3.5" strokeWidth={2} /> New document
        </button>
        <button onClick={() => { refreshList(); refreshPending(); invalidateKnowledge(); }} className="kb-btn kb-btn-ghost">
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} strokeWidth={1.5} /> Refresh
        </button>
        <div className="kb-hstat ml-2"><span className="n">{active.length}</span><span className="l">docs</span></div>
        <div className="kb-hstat"><span className="n" style={{ color: pendingCount ? "var(--color-warning)" : undefined }}>{pendingCount}</span><span className="l">to review</span></div>
      </div>

      {creating && (
        <CreateDocForm
          onCancel={() => setCreating(false)}
          onCreated={(doc) => { setCreating(false); setSelectedId(doc.id); syncEntry(doc.id); refreshList(); invalidateKnowledge(); }}
        />
      )}

      {/* Three-pane workspace */}
      <div className="kb-split flex flex-1 min-h-0">
        <CategoryNav
          docs={active}
          pendingCount={pendingCount}
          archivedCount={archived.length}
          nav={nav}
          search={searchQ}
          onSearch={(q) => setSearchQ(q)}
          onCategory={selectCategory}
          onManage={selectManage}
          scopeFilter={scopeFilter}
          onScopeFilter={setScopeFilter}
        />

        {/* List column */}
        <DocList
          icon={listIcon}
          title={listTitle}
          countLabel={listCount}
          subtitle={listSubtitle}
          showControls={listControls}
          list={list}
          sortBy={sortBy}
          onCycleSort={cycleSort}
          filters={filters}
          onToggleFilter={toggleFilter}
          selectedId={selectedId}
          onSelect={handleSelectDoc}
          showScope={showScope}
        />

        {/* Reader column */}
        <div className="kb-reader">
          {!selectedId ? (
            <QuickPick docs={active} pending={pendingDocs} onSelect={handleSelectDoc} onSelectCategory={selectCategory} />
          ) : !selectedDoc ? (
            <div className="kb-reader-loading"><Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-dim)]" /></div>
          ) : editMode ? (
            <>
              <div className="kb-reader-bar">
                <span className="kb-reader-path"><KbIcon name="edit" size={13} />Editing<span className="f"> {selectedDoc.title}.md</span></span>
                <div className="act">
                  <button
                    className="kb-btn kb-btn-ghost"
                    onClick={() => { if (editBuffer !== (selectedDoc.body ?? "")) setDirtyConfirm(true); else setEditMode(false); }}
                  >Cancel</button>
                  <button className="kb-btn kb-btn-primary" onClick={handleSave} disabled={saving}>
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <KbIcon name="check" size={14} />}
                    {saving ? "Saving…" : "Save"}
                  </button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto kb-editor">
                <div className="kb-editor-inner">
                  <textarea
                    autoFocus
                    value={editBuffer}
                    onChange={(e) => setEditBuffer(e.target.value)}
                    onKeyDown={handleEditKeyDown}
                    spellCheck={false}
                  />
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="kb-reader-bar">
                <span className="kb-reader-path"><KbIcon name="doc" size={13} />{docPath(selectedDoc)} /<span className="f"> {selectedDoc.title}.md</span></span>
                <div className="act">
                  <button className="kb-btn" onClick={() => setHistoryOpen(true)}><KbIcon name="history" size={14} />History</button>
                  {selectedDoc.status === "pending" ? (
                    <>
                      <button className="kb-btn kb-btn-danger" onClick={() => setConfirmArchive(true)}><KbIcon name="slash" size={14} />Deny</button>
                      <button className="kb-btn kb-btn-primary" onClick={() => setConfirmApprove(true)}><KbIcon name="check" size={14} />Approve</button>
                    </>
                  ) : (
                    <>
                      <button className="kb-btn kb-btn-danger" onClick={() => setConfirmArchive(true)}><KbIcon name="archive" size={14} />Archive</button>
                      <button className="kb-btn kb-btn-primary" onClick={() => setEditMode(true)}><KbIcon name="edit" size={14} />Edit</button>
                    </>
                  )}
                </div>
              </div>
              <DocumentView
                doc={selectedDoc}
                docs={active}
                backlinks={backlinksFor(selectedDoc.id)}
                onNavigate={handleSelectDoc}
              />
            </>
          )}
        </div>
      </div>

      {historyOpen && selectedDoc && (
        <HistoryModal doc={selectedDoc} edits={edits ?? []} onClose={() => setHistoryOpen(false)} onRevert={handleRevert} />
      )}

      <ConfirmDialog
        open={confirmArchive}
        title={selectedDoc?.status === "pending" ? "deny document" : "archive document"}
        message={selectedDoc ? `${selectedDoc.status === "pending" ? "deny and archive" : "archive"} "${selectedDoc.title}"? this removes it from the active knowledge base.` : "archive this document?"}
        confirmLabel={selectedDoc?.status === "pending" ? "deny" : "archive"}
        variant="danger"
        onConfirm={() => { setConfirmArchive(false); handleArchive(); }}
        onCancel={() => setConfirmArchive(false)}
      />
      <ConfirmDialog
        open={confirmApprove}
        title="approve document"
        message={selectedDoc ? `approve "${selectedDoc.title}"? it will become active and readable by agents.` : "approve this document?"}
        confirmLabel="approve"
        variant="default"
        onConfirm={() => { setConfirmApprove(false); if (selectedId) handleApprove(selectedId); }}
        onCancel={() => setConfirmApprove(false)}
      />
      <ConfirmDialog
        open={dirtyConfirm}
        title="unsaved changes"
        message="you have unsaved changes. discard and continue?"
        confirmLabel="discard"
        variant="danger"
        onConfirm={() => {
          setDirtyConfirm(false); setEditMode(false);
          if (pendingSelectId) { setSelectedId(pendingSelectId); syncEntry(pendingSelectId); setPendingSelectId(null); }
        }}
        onCancel={() => { setDirtyConfirm(false); setPendingSelectId(null); }}
      />
    </div>
  );
}

export default function KnowledgePageWrapper() {
  return (
    <Suspense fallback={null}>
      <KnowledgePage />
    </Suspense>
  );
}
