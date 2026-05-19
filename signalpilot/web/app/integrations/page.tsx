"use client";

import { useEffect, useState, useCallback } from "react";
import {
  BookOpen,
  Plus,
  Trash2,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  X,
  TestTube,
  Pencil,
} from "lucide-react";
import { useAppAuth } from "@/lib/auth-context";
import {
  getNotionIntegrations,
  createNotionIntegration,
  updateNotionIntegration,
  deleteNotionIntegration,
  testNotionIntegration,
  type NotionIntegration,
} from "@/lib/api";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { ApiKeysSkeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parsePageId(input: string): string {
  const cleaned = input.trim();
  const match = cleaned.match(/([a-f0-9]{32})/i);
  if (match) return match[1];
  const stripped = cleaned.replace(/-/g, "");
  if (/^[a-f0-9]{32}$/i.test(stripped)) return stripped;
  return cleaned;
}

// ---------------------------------------------------------------------------
// Gate
// ---------------------------------------------------------------------------

export default function IntegrationsPage() {
  const { isLoaded } = useAppAuth();
  if (!isLoaded) return <ApiKeysSkeleton />;
  return <IntegrationsContent />;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function IntegrationsContent() {
  const { toast } = useToast();

  const [integrations, setIntegrations] = useState<NotionIntegration[]>([]);
  const [loading, setLoading] = useState(true);

  // Form
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formApiKey, setFormApiKey] = useState("");
  const [formSearchPages, setFormSearchPages] = useState<string[]>([]);
  const [formPageInput, setFormPageInput] = useState("");
  const [formReportPage, setFormReportPage] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Edit
  const [editingName, setEditingName] = useState<string | null>(null);

  // Test / delete
  const [testingName, setTestingName] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { status: string; message: string }>>({});
  const [deletingName, setDeletingName] = useState<string | null>(null);

  const fetchIntegrations = useCallback(async () => {
    try {
      setIntegrations(await getNotionIntegrations());
    } catch {
      toast("failed to load integrations", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { fetchIntegrations(); }, [fetchIntegrations]);

  // ── Add page URL to search scope ──
  function handleAddPage() {
    const id = parsePageId(formPageInput);
    if (!id) return;
    if (formSearchPages.includes(id)) {
      setFormError("page already added");
      return;
    }
    setFormSearchPages((prev) => [...prev, id]);
    setFormPageInput("");
    setFormError(null);
  }

  // ── Create ──
  async function handleCreate() {
    if (!formName.trim()) { setFormError("name is required"); return; }
    if (!formApiKey.trim()) { setFormError("access token is required"); return; }
    if (!formReportPage.trim()) { setFormError("report destination is required"); return; }

    setCreating(true);
    setFormError(null);
    try {
      await createNotionIntegration({
        name: formName.trim(),
        api_key: formApiKey.trim(),
        search_page_ids: formSearchPages,
        report_parent_page_id: parsePageId(formReportPage),
      });
      toast("notion integration created", "success");
      setShowForm(false);
      setFormName("");
      setFormApiKey("");
      setFormSearchPages([]);
      setFormPageInput("");
      setFormReportPage("");
      await fetchIntegrations();
    } catch (e) {
      setFormError(String(e));
    } finally {
      setCreating(false);
    }
  }

  function handleStartEdit(integration: NotionIntegration) {
    setEditingName(integration.name);
    setShowForm(true);
    setFormName(integration.name);
    setFormApiKey("");
    setFormSearchPages([...integration.search_page_ids]);
    setFormReportPage(integration.report_parent_page_id || "");
    setFormError(null);
  }

  async function handleSaveEdit() {
    if (!editingName) return;
    if (!formReportPage.trim()) { setFormError("report destination is required"); return; }

    setCreating(true);
    setFormError(null);
    const updates: Record<string, unknown> = {
      search_page_ids: formSearchPages,
      report_parent_page_id: parsePageId(formReportPage),
    };
    if (formApiKey.trim()) {
      updates.api_key = formApiKey.trim();
    }
    try {
      await updateNotionIntegration(editingName, updates);
      toast("integration updated", "success");
      setShowForm(false);
      setEditingName(null);
      setFormName("");
      setFormApiKey("");
      setFormSearchPages([]);
      setFormPageInput("");
      setFormReportPage("");
      await fetchIntegrations();
    } catch (e) {
      setFormError(String(e));
    } finally {
      setCreating(false);
    }
  }

  async function handleTest(name: string) {
    setTestingName(name);
    try {
      const result = await testNotionIntegration(name);
      setTestResults((prev) => ({ ...prev, [name]: result }));
      toast(result.status === "ok" ? "connected" : "connection failed", result.status === "ok" ? "success" : "error");
    } catch (e) {
      setTestResults((prev) => ({ ...prev, [name]: { status: "error", message: String(e) } }));
      toast("test failed", "error");
    } finally {
      setTestingName(null);
    }
  }

  async function handleDelete(name: string) {
    try {
      await deleteNotionIntegration(name);
      toast("deleted", "success");
      setDeletingName(null);
      await fetchIntegrations();
    } catch (e) {
      toast(`failed: ${e}`, "error");
    }
  }

  if (loading) return <ApiKeysSkeleton />;

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="integrations"
        subtitle="notion"
        description="connect external services to signalpilot"
      />

      <TerminalBar
        path="integrations --list"
        status={<StatusDot status={integrations.length > 0 ? "healthy" : "unknown"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            active: <code className="text-[12px] text-[var(--color-text)]">{integrations.length}</code>
          </span>
        </div>
      </TerminalBar>

      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <SectionHeader icon={BookOpen} title="notion" />
          {!showForm && (
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              <Plus className="w-3 h-3" />
              add
            </button>
          )}
        </div>

        {/* ── Create form ── */}
        {showForm && (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-4 animate-fade-in">
            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="block text-[11px] text-[var(--color-text-dim)] mb-1.5 tracking-[0.15em] uppercase">name</label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Escape") { setShowForm(false); setEditingName(null); setFormName(""); setFormApiKey(""); setFormSearchPages([]); setFormPageInput(""); setFormReportPage(""); setFormError(null); } }}
                  placeholder="e.g. data-team"
                  autoFocus={!editingName}
                  readOnly={!!editingName}
                  className={`w-full px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] focus:outline-none focus:border-[var(--color-text-dim)] tracking-wider ${editingName ? "opacity-50 cursor-not-allowed" : ""}`}
                />
              </div>

              {/* Access Token */}
              <div>
                <label className="block text-[11px] text-[var(--color-text-dim)] mb-1.5 tracking-[0.15em] uppercase">access token</label>
                <input
                  type="password"
                  value={formApiKey}
                  onChange={(e) => setFormApiKey(e.target.value)}
                  placeholder={editingName ? "leave blank to keep current" : "ntn_..."}
                  className="w-full px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] focus:outline-none focus:border-[var(--color-text-dim)] tracking-wider font-mono"
                />
              </div>

              {/* Search scope — add one at a time */}
              <div>
                <label className="block text-[11px] text-[var(--color-text-dim)] mb-1.5 tracking-[0.15em] uppercase">search scope</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={formPageInput}
                    onChange={(e) => setFormPageInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAddPage(); } }}
                    placeholder="paste notion page url"
                    className="flex-1 px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] focus:outline-none focus:border-[var(--color-text-dim)] tracking-wider font-mono"
                  />
                  <button
                    onClick={handleAddPage}
                    className="flex items-center gap-1.5 px-3 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
                  >
                    <Plus className="w-3 h-3" />
                    add
                  </button>
                </div>
                {/* Added pages */}
                {formSearchPages.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {formSearchPages.map((id) => (
                      <div key={id} className="flex items-center gap-2 px-3 py-1.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[12px] font-mono tracking-wider">
                        <span className="flex-1 text-[var(--color-text-muted)] truncate">{id}</span>
                        <button
                          onClick={() => setFormSearchPages((prev) => prev.filter((p) => p !== id))}
                          className="text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-colors"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Report destination */}
              <div>
                <label className="block text-[11px] text-[var(--color-text-dim)] mb-1.5 tracking-[0.15em] uppercase">report destination</label>
                <input
                  type="text"
                  value={formReportPage}
                  onChange={(e) => setFormReportPage(e.target.value)}
                  placeholder="paste notion page url"
                  className="w-full px-3 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] focus:outline-none focus:border-[var(--color-text-dim)] tracking-wider font-mono"
                />
              </div>

              {/* Error */}
              {formError && (
                <div className="flex items-start gap-2 p-3 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5">
                  <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
                  <p className="text-[12px] text-[var(--color-error)] tracking-wider">{formError}</p>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-3">
                <button
                  onClick={editingName ? handleSaveEdit : handleCreate}
                  disabled={creating}
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
                >
                  {creating ? <Loader2 className="w-3 h-3 animate-spin" /> : editingName ? <Pencil className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                  {editingName ? "save" : "create"}
                </button>
                <button
                  onClick={() => { setShowForm(false); setFormError(null); setEditingName(null); setFormName(""); setFormApiKey(""); setFormSearchPages([]); setFormPageInput(""); setFormReportPage(""); }}
                  disabled={creating}
                  className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider uppercase"
                >
                  cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Empty state ── */}
        {integrations.length === 0 && !showForm && (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-8 text-center">
            <BookOpen className="w-6 h-6 text-[var(--color-text-dim)] mx-auto mb-3" strokeWidth={1} />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider mb-3">
              no integrations configured
            </p>
            <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider leading-relaxed max-w-md mx-auto">
              create a notion integration at{" "}
              <a href="https://www.notion.so/profile/integrations" target="_blank" rel="noopener noreferrer" className="text-[var(--color-text-muted)] underline underline-offset-2 hover:text-[var(--color-text)] transition-colors">
                notion.so/profile/integrations
              </a>
              {" "}to get an api key, then share your pages with it
            </p>
          </div>
        )}

        {/* ── Cards ── */}
        {integrations.map((integration) => {
          const testResult = testResults[integration.name];
          return (
            <div key={integration.id} className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 mb-3">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2">
                    <BookOpen className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
                    <span className="text-[13px] text-[var(--color-text)] tracking-wider font-medium">{integration.name}</span>
                    {testResult && (
                      testResult.status === "ok"
                        ? <CheckCircle2 className="w-3 h-3 text-[var(--color-success)]" />
                        : <AlertTriangle className="w-3 h-3 text-[var(--color-error)]" />
                    )}
                  </div>
                  <div className="space-y-1 text-[11px] text-[var(--color-text-dim)] tracking-wider">
                    <p>search scope: <span className="text-[var(--color-text-muted)]">{integration.search_page_ids.length} page{integration.search_page_ids.length !== 1 ? "s" : ""}</span></p>
                    <p>report: <span className="text-[var(--color-text-muted)] font-mono">{integration.report_parent_page_id ? integration.report_parent_page_id.slice(0, 12) + "..." : "—"}</span></p>
                  </div>
                  {testResult && testResult.status !== "ok" && (
                    <p className="text-[11px] text-[var(--color-error)] mt-2 tracking-wider">{testResult.message}</p>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleTest(integration.name)}
                    disabled={testingName === integration.name}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase disabled:opacity-30"
                  >
                    {testingName === integration.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <TestTube className="w-3 h-3" />}
                    test
                  </button>
                  <button
                    onClick={() => handleStartEdit(integration)}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
                  >
                    <Pencil className="w-3 h-3" />
                    edit
                  </button>
                  {deletingName === integration.name ? (
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => handleDelete(integration.name)} className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/30 hover:border-[var(--color-error)] transition-all tracking-wider uppercase">confirm</button>
                      <button onClick={() => setDeletingName(null)} className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"><X className="w-3 h-3" /></button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setDeletingName(integration.name)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)]/50 hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
                    >
                      <Trash2 className="w-3 h-3" />
                      delete
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
