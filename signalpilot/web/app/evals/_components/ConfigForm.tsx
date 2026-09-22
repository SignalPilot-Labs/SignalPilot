"use client";

/** Eval configuration form: eval repo, dbt project repo, model, connection, notifications, autorun. */

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Loader2, Save } from "lucide-react";
import { getEvalConfig, getGitHubInstallations, putEvalConfig, type EvalConfig } from "~/lib/api";
import { useToast } from "~/components/ui/toast";
import { usePermissions } from "~/lib/hooks/use-permissions";
import { useAppAuth } from "~/lib/auth-context";
import { ReadOnlyNote } from "~/components/access/read-only-note";
import { useGitHubConnect, type RepoPickerStyles } from "./RepoPicker";
import {
  EMPTY_PROJECT_REPO,
  ProjectRepoFields,
  projectRepoError,
  projectRepoFromConfig,
  projectRepoPayload,
  type ProjectRepoValue,
} from "./ProjectRepoFields";

/** The config as values only: what a member sees where the admin form is. */
function ConfigValues({ config }: { config?: EvalConfig }) {
  const rows: [string, string][] = [
    ["Repo", config?.repo_url || "—"],
    ["dbt project", config?.project_repo_url || "not set"],
    ["Project branch", config?.project_ref || "repository default"],
    ["Model", config?.model || "sonnet"],
    ["Max tasks per run", String(config?.max_tasks ?? 0) + ((config?.max_tasks ?? 0) === 0 ? " (all)" : "")],
    ["Connection", config?.connection || "—"],
    ["Notify emails", (config?.notify_emails ?? []).join(", ") || "—"],
    ["Prompt preamble", config?.prompt_preamble || "—"],
    ["Autorun on knowledge add", config?.autorun_on_knowledge_add ? "on" : "off"],
  ];
  return (
    <div className="mt-4 pt-4 border-t border-[var(--color-border)] space-y-3" data-testid="eval-config-values">
      <ReadOnlyNote block>eval repo, dbt project, model, connection, and run policy</ReadOnlyNote>
      <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-xs text-[var(--color-text-muted)] mb-0.5">{label}</dt>
            <dd className="text-[var(--color-text)] break-words">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ConfigForm({ onSaved }: { onSaved: () => void }) {
  const { can } = usePermissions();
  if (!can("evals.run")) return <ConfigValuesLoader />;
  return <ConfigEditor onSaved={onSaved} />;
}

function ConfigValuesLoader() {
  const { data } = useSWR("eval-config", getEvalConfig);
  return <ConfigValues config={data} />;
}

const inputCls =
  "w-full bg-transparent border border-[var(--color-border)] rounded-[10px] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] focus:outline-none";
const labelCls = "block text-xs text-[var(--color-text-muted)] mb-1.5";
const pickerStyles: RepoPickerStyles = { field: "block", label: labelCls, control: inputCls };

function ConfigEditor({ onSaved }: { onSaved: () => void }) {
  const { toast } = useToast();
  const { isCloudMode } = useAppAuth();
  const { data, mutate } = useSWR("eval-config", getEvalConfig);
  const { data: installations, isLoading: installationsLoading } = useSWR(
    "github-installations",
    getGitHubInstallations,
  );
  const [form, setForm] = useState({
    repo_url: "",
    repo_installation_id: null as string | null,
    repo_id: null as number | null,
    project: EMPTY_PROJECT_REPO as ProjectRepoValue,
    model: "sonnet",
    max_tasks: 0,
    prompt_preamble: "",
    connection: "",
    notify_emails: "",
    autorun_on_knowledge_add: false,
  });
  const [savingCfg, setSavingCfg] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const { connectGitHub, connecting: connectingGitHub } = useGitHubConnect(
    "/evals",
    (message) => toast(message, "error"),
  );

  useEffect(() => {
    if (data && !loaded) {
      setForm({
        repo_url: data.repo_url ?? "",
        repo_installation_id: data.repo_installation_id ?? null,
        repo_id: data.repo_id ?? null,
        project: projectRepoFromConfig(data),
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
    const projectMessage = projectRepoError(form.project, isCloudMode);
    if (projectMessage) {
      toast(projectMessage, "error");
      return;
    }
    setSavingCfg(true);
    try {
      await putEvalConfig({
        repo_url: form.repo_url,
        repo_installation_id: form.repo_installation_id,
        repo_id: form.repo_id,
        ...projectRepoPayload(form.project),
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

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t border-[var(--color-border)]">
      <div className="md:col-span-2">
        <label className={labelCls}>
          {isCloudMode
            ? "Eval repo: public git URL (format: eval-format.md)"
            : "Eval repo: public git URL, or a local path under /eval-projects (format: eval-format.md)"}
        </label>
        <input
          className={inputCls}
          data-testid="eval-repo-url"
          value={form.repo_url}
          onChange={(e) => setForm({ ...form, repo_url: e.target.value, repo_installation_id: null, repo_id: null })}
          placeholder={isCloudMode ? "https://github.com/org/eval-set" : "https://github.com/org/eval-set.git  ·  /eval-projects/northwind"}
        />
      </div>
      <div className="md:col-span-2 space-y-3">
        <div>
          <p className="text-xs text-[var(--color-text-muted)]">dbt project repository</p>
          <p className="text-xs text-[var(--color-text-dim)] mt-0.5">
            The eval set runs against this dbt project. SignalPilot clones it for every run.
          </p>
        </div>
        <ProjectRepoFields
          value={form.project}
          onChange={(project) => setForm({ ...form, project })}
          installations={installations}
          installationsLoading={installationsLoading}
          onConnectGitHub={connectGitHub}
          connectingGitHub={connectingGitHub}
          isCloudMode={isCloudMode}
          styles={pickerStyles}
        />
      </div>
      <div>
        <label className={labelCls}>Model</label>
        <input className={inputCls} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="sonnet" />
      </div>
      <div>
        <label className={labelCls}>Max tasks per run (0 = all)</label>
        <input className={inputCls} type="number" min={0} max={200} value={form.max_tasks} onChange={(e) => setForm({ ...form, max_tasks: Number(e.target.value) || 0 })} />
      </div>
      <div>
        <label className={labelCls}>Connection — warehouse connection the graded agent must use</label>
        <input required className={inputCls} value={form.connection} onChange={(e) => setForm({ ...form, connection: e.target.value })} placeholder="northwind_ro_conn" />
      </div>
      <div>
        <label className={labelCls}>Notify emails — comma-separated, alerted on accuracy regressions</label>
        <input className={inputCls} value={form.notify_emails} onChange={(e) => setForm({ ...form, notify_emails: e.target.value })} placeholder="data-team@acme.com, oncall@acme.com" />
      </div>
      <div className="md:col-span-2">
        <label className={labelCls}>Prompt preamble — prepended to every task (connection to use, output rules)</label>
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
        <button onClick={save} disabled={savingCfg} data-testid="eval-config-save" className="inline-flex items-center gap-2 px-4 py-2 rounded-[10px] text-sm border border-[var(--color-border-hover)] text-[var(--color-text)] hover:bg-[var(--color-bg)] disabled:opacity-40 transition-colors">
          {savingCfg ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" strokeWidth={1.5} />}
          Save config
        </button>
      </div>
    </div>
  );
}
