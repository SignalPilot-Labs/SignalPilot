"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import type { KnowledgeDoc } from "~/lib/types";
import { createKnowledgeDoc, getConnections, getProjects } from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import { SCOPE_CATEGORIES, CATEGORY_META } from "./categories";
import { KbIcon } from "./icons";

export function CreateDocForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (doc: KnowledgeDoc) => void;
}) {
  const { toast } = useToast();
  const [scope, setScope] = useState<KnowledgeDoc["scope"]>("org");
  const [scopeRef, setScopeRef] = useState("");
  const [category, setCategory] = useState<KnowledgeDoc["category"]>("decisions");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [projects, setProjects] = useState<string[]>([]);
  const [connections, setConnections] = useState<string[]>([]);

  useEffect(() => {
    getProjects().then((p) => setProjects(p.map((x) => x.name))).catch(() => {});
    getConnections().then((c) => setConnections(c.map((x) => x.name))).catch(() => {});
  }, []);

  const allowedCategories = SCOPE_CATEGORIES[scope];

  useEffect(() => {
    if (!allowedCategories.includes(category)) setCategory(allowedCategories[0]);
  }, [scope, allowedCategories, category]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const doc = await createKnowledgeDoc({
        scope,
        scope_ref: scope === "org" ? null : (scopeRef || null),
        category,
        title: title.trim(),
        body,
      });
      toast("doc created", "success");
      onCreated(doc);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown error";
      if (msg.includes("409")) setError("a doc with this title already exists in this scope/category");
      else if (msg.includes("403")) toast("admin scope required", "error");
      else setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  const refs = scope === "project" ? projects : scope === "connection" ? connections : [];

  return (
    <div className="kb-panel p-5 mb-4 animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <span className="text-[14px] font-semibold text-[var(--color-text)]">New document</span>
        <button onClick={onCancel} aria-label="cancel" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
          <KbIcon name="close" size={16} />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="kb-label">Scope</label>
            <select value={scope} onChange={(e) => setScope(e.target.value as KnowledgeDoc["scope"])} className="kb-select">
              <option value="org">org</option>
              <option value="project">project</option>
              <option value="connection">connection</option>
            </select>
          </div>
          <div>
            <label className="kb-label">Scope ref</label>
            {scope === "org" ? (
              <input disabled value="—" className="kb-input opacity-40" />
            ) : refs.length > 0 ? (
              <select value={scopeRef} onChange={(e) => setScopeRef(e.target.value)} className="kb-select">
                <option value="">select…</option>
                {refs.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            ) : (
              <input
                type="text"
                value={scopeRef}
                onChange={(e) => setScopeRef(e.target.value)}
                placeholder={scope === "project" ? "project name" : "connection name"}
                className="kb-input"
              />
            )}
          </div>
          <div>
            <label className="kb-label">Category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value as KnowledgeDoc["category"])} className="kb-select">
              {allowedCategories.map((c) => <option key={c} value={c}>{CATEGORY_META[c].label}</option>)}
            </select>
          </div>
        </div>
        <div>
          <label className="kb-label">
            Title <span className="kb-hint">— lowercase, hyphenated (e.g. postgres-naming-conventions)</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="e.g. postgres-naming-conventions"
            className="kb-input"
          />
        </div>
        <div>
          <label className="kb-label">Body <span className="kb-hint">— markdown</span></label>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={8} className="kb-input font-mono resize-y" />
        </div>
        {error && <p className="text-[12px] text-[var(--color-error)]">{error}</p>}
        <div className="flex items-center gap-2 pt-1">
          <button type="submit" disabled={submitting || !title.trim()} className="kb-btn kb-btn-primary">
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Create document
          </button>
          <button type="button" onClick={onCancel} className="kb-btn kb-btn-ghost">Cancel</button>
        </div>
      </form>
    </div>
  );
}
