"use client";

/** Eval configuration form: repo, model, connection, notifications, autorun. */

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Loader2, Save } from "lucide-react";
import { getEvalConfig, putEvalConfig } from "~/lib/api";
import { useToast } from "~/components/ui/toast";

export function ConfigForm({ onSaved }: { onSaved: () => void }) {
  const { toast } = useToast();
  const { data, mutate } = useSWR("eval-config", getEvalConfig);
  const [form, setForm] = useState({
    repo_url: "",
    repo_installation_id: null as string | null,
    repo_id: null as number | null,
    model: "sonnet",
    max_tasks: 0,
    prompt_preamble: "",
    connection: "",
    notify_emails: "",
    autorun_on_knowledge_add: false,
  });
  const [savingCfg, setSavingCfg] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (data && !loaded) {
      setForm({
        repo_url: data.repo_url ?? "",
        repo_installation_id: data.repo_installation_id ?? null,
        repo_id: data.repo_id ?? null,
        model: data.model ?? "sonnet",
        max_tasks: data.max_tasks ?? 0,
        prompt_preamble: data.prompt_preamble ?? "",
        connection: data.connection ?? "",
        notify_emails: (data.notify_emails ?? []).join(", "),
        autorun_on_knowledge_add: data.autorun_on_knowledge_add ?? false,
      });
      setLoaded(true);
    }
  }, [data, loaded]);

  async function save() {
    setSavingCfg(true);
    try {
      await putEvalConfig({
        repo_url: form.repo_url,
        repo_installation_id: form.repo_installation_id,
        repo_id: form.repo_id,
        model: form.model,
        max_tasks: form.max_tasks,
        prompt_preamble: form.prompt_preamble,
        connection: form.connection,
        autorun_on_knowledge_add: form.autorun_on_knowledge_add,
        notify_emails: form.notify_emails
          .split(",")
          .map((e) => e.trim())
          .filter(Boolean),
      });
      await mutate();
      toast("eval config saved", "success");
      onSaved();
    } catch (err) {
      toast(`save failed: ${err instanceof Error ? err.message : "unknown"}`, "error");
    } finally {
      setSavingCfg(false);
    }
  }

  const inputCls =
    "w-full bg-transparent border border-[var(--color-border)] rounded-[10px] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] focus:outline-none";

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t border-[var(--color-border)]">
      <div className="md:col-span-2">
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">
          Repo — public git URL, or a local path under /eval-projects (format: eval-format.md)
        </label>
        <input className={inputCls} value={form.repo_url} onChange={(e) => setForm({ ...form, repo_url: e.target.value, repo_installation_id: null, repo_id: null })} placeholder="https://github.com/org/eval-set.git  ·  /eval-projects/northwind" />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Model</label>
        <input className={inputCls} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="sonnet" />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Max tasks per run (0 = all)</label>
        <input className={inputCls} type="number" min={0} max={200} value={form.max_tasks} onChange={(e) => setForm({ ...form, max_tasks: Number(e.target.value) || 0 })} />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Connection — warehouse connection the graded agent must use</label>
        <input required className={inputCls} value={form.connection} onChange={(e) => setForm({ ...form, connection: e.target.value })} placeholder="northwind_ro_conn" />
      </div>
      <div>
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Notify emails — comma-separated, alerted on accuracy regressions</label>
        <input className={inputCls} value={form.notify_emails} onChange={(e) => setForm({ ...form, notify_emails: e.target.value })} placeholder="data-team@acme.com, oncall@acme.com" />
      </div>
      <div className="md:col-span-2">
        <label className="block text-xs text-[var(--color-text-muted)] mb-1.5">Prompt preamble — prepended to every task (connection to use, output rules)</label>
        <textarea className={`${inputCls} resize-none`} rows={2} value={form.prompt_preamble} onChange={(e) => setForm({ ...form, prompt_preamble: e.target.value })} placeholder='e.g. "Use the SignalPilot MCP tools with connection northwind_ro_conn."' />
      </div>
      <div className="md:col-span-2">
        <label className="flex items-start gap-2.5 cursor-pointer group">
          <input
            type="checkbox"
            className="mt-0.5 accent-[var(--color-success)]"
            checked={form.autorun_on_knowledge_add}
            onChange={(e) => setForm({ ...form, autorun_on_knowledge_add: e.target.checked })}
          />
          <span>
            <span className="block text-sm text-[var(--color-text)]">
              Autorun whenever a knowledge base entry is added
            </span>
            <span className="block text-xs text-[var(--color-text-muted)] mt-0.5">
              Grades the whole set against the live knowledge base when an entry is approved or
              added. Pending entries don’t trigger it — evaluate those from the knowledge page.
              Repeated additions coalesce into one run every 2 minutes.
            </span>
          </span>
        </label>
      </div>
      <div>
        <button onClick={save} disabled={savingCfg} className="inline-flex items-center gap-2 px-4 py-2 rounded-[10px] text-sm border border-[var(--color-border-hover)] text-[var(--color-text)] hover:bg-[var(--color-bg)] disabled:opacity-40 transition-colors">
          {savingCfg ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" strokeWidth={1.5} />}
          Save config
        </button>
      </div>
    </div>
  );
}
