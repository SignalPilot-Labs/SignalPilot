"use client";

import {
  GitBranch,
  Hammer,
  Loader2,
  Save,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { useToast } from "~/components/ui/toast";
import {
  compileDbtMap,
  getDbtMap,
  getDbtProjectDir,
  updateWorkspaceProject,
} from "~/lib/api";
import type { DbtMapInfo, WorkspaceProjectInfo } from "~/lib/types";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

const AUTO = "__auto__";

export function ProjectAutomationSettings({
  project,
  onProjectUpdated,
}: {
  project: WorkspaceProjectInfo;
  onProjectUpdated: (next: WorkspaceProjectInfo) => void;
}) {
  const { toast } = useToast();
  const settings = (project.settings ?? {}) as Record<string, unknown>;

  const [detectedDirs, setDetectedDirs] = useState<string[]>([]);
  const [dbtDir, setDbtDir] = useState<string>(
    typeof settings.dbt_project_dir === "string" ? settings.dbt_project_dir : AUTO,
  );
  const [watchedBranches, setWatchedBranches] = useState<string[]>(
    Array.isArray(settings.watched_branches)
      ? (settings.watched_branches as string[])
      : [project.default_branch || "main"],
  );
  const [branchInput, setBranchInput] = useState("");
  const [autoCompileOnPush, setAutoCompileOnPush] = useState(
    settings.auto_compile_on_push !== false,
  );
  const [compileOnPr, setCompileOnPr] = useState(settings.compile_on_pr === true);
  const [prAgentTrigger, setPrAgentTrigger] = useState(
    settings.pr_agent_trigger === true,
  );
  const [saving, setSaving] = useState(false);
  const [mapInfo, setMapInfo] = useState<DbtMapInfo | null>(null);
  const [mapStatus, setMapStatus] = useState<string>("none");
  const [compiling, setCompiling] = useState(false);

  useEffect(() => {
    let active = true;
    void getDbtProjectDir(project.id, project.default_branch || undefined)
      .then((res) => {
        if (active) setDetectedDirs(res.detected);
      })
      .catch(() => {});
    void getDbtMap(project.id, undefined, false)
      .then((res) => {
        if (!active) return;
        setMapStatus(res.status);
        setMapInfo(res.map);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [project.id, project.default_branch]);

  const addBranch = () => {
    const name = branchInput.trim();
    if (!name || watchedBranches.includes(name)) {
      setBranchInput("");
      return;
    }
    setWatchedBranches([...watchedBranches, name]);
    setBranchInput("");
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const nextSettings: Record<string, unknown> = {
        ...settings,
        watched_branches: watchedBranches,
        auto_compile_on_push: autoCompileOnPush,
        compile_on_pr: compileOnPr,
        pr_agent_trigger: prAgentTrigger,
      };
      if (dbtDir === AUTO) {
        delete nextSettings.dbt_project_dir;
      } else {
        nextSettings.dbt_project_dir = dbtDir;
      }
      const updated = await updateWorkspaceProject(project.id, {
        settings: nextSettings,
      });
      onProjectUpdated(updated);
      toast("Project automation settings saved", "success");
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      setSaving(false);
    }
  };

  const compileNow = async () => {
    if (compiling) return;
    setCompiling(true);
    try {
      await compileDbtMap(project.id);
      toast("dbt map compile started on a sandbox", "success");
      setMapStatus("running");
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      setCompiling(false);
    }
  };

  return (
    <section className="mt-6 overflow-hidden rounded-[14px] border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      <div className="border-b border-[var(--color-border)] p-6">
        <div className="flex items-start gap-3">
          <Workflow className="mt-0.5 h-4 w-4 text-[var(--color-success)]" />
          <div>
            <h2 className="text-sm font-medium text-[var(--color-text)]">
              dbt project &amp; automation
            </h2>
            <p className="mt-1 text-xs leading-5 text-[var(--color-text-dim)]">
              Where the dbt project lives in this repo, which branches trigger
              automatic dbt map recompiles, and what happens on pull requests.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-5 p-6">
        {/* dbt project folder */}
        <div>
          <label
            htmlFor="project-dbt-dir"
            className="mb-1.5 block text-xs text-[var(--color-text-dim)]"
          >
            dbt project folder
          </label>
          <select
            id="project-dbt-dir"
            value={dbtDir}
            onChange={(event) => setDbtDir(event.target.value)}
            className="w-full rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 text-sm text-[var(--color-text)] focus:border-[var(--color-text-dim)] focus:outline-none"
          >
            <option value={AUTO}>
              Auto-detect{detectedDirs.length > 0 ? ` (${detectedDirs[0] === "" ? "repo root" : detectedDirs[0]})` : ""}
            </option>
            {detectedDirs.map((dir) => (
              <option key={dir || "."} value={dir}>
                {dir === "" ? "repo root" : dir}
              </option>
            ))}
          </select>
          {detectedDirs.length === 0 && (
            <p className="mt-1.5 text-[11px] text-[var(--color-text-dim)]">
              No dbt_project.yml detected on the default branch yet.
            </p>
          )}
        </div>

        {/* Watched branches */}
        <div>
          <span className="mb-1.5 block text-xs text-[var(--color-text-dim)]">
            Watched branches
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            {watchedBranches.map((branch) => (
              <span
                key={branch}
                className="inline-flex items-center gap-1 rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1 text-[11px] text-[var(--color-text)]"
              >
                <GitBranch className="h-3 w-3 text-[var(--color-text-dim)]" />
                {branch}
                <button
                  type="button"
                  onClick={() =>
                    setWatchedBranches(watchedBranches.filter((b) => b !== branch))
                  }
                  className="ml-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)]"
                  aria-label={`Stop watching ${branch}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            <input
              value={branchInput}
              onChange={(event) => setBranchInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addBranch();
                }
              }}
              onBlur={addBranch}
              placeholder="add branch…"
              className="w-32 rounded-[8px] border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1 text-[11px] text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:outline-none"
            />
          </div>
          <p className="mt-1.5 text-[11px] text-[var(--color-text-dim)]">
            Pushes to these branches trigger automation. GitHub webhooks must be
            enabled on the linked repo.
          </p>
        </div>

        {/* Automation toggles */}
        <div className="space-y-2.5">
          <label className="flex items-center gap-2.5 text-xs text-[var(--color-text)]">
            <input
              type="checkbox"
              checked={autoCompileOnPush}
              onChange={(event) => setAutoCompileOnPush(event.target.checked)}
              className="h-3.5 w-3.5"
            />
            Recompile the dbt map on pushes to watched branches
          </label>
          <label className="flex items-center gap-2.5 text-xs text-[var(--color-text)]">
            <input
              type="checkbox"
              checked={compileOnPr}
              onChange={(event) => setCompileOnPr(event.target.checked)}
              className="h-3.5 w-3.5"
            />
            Compile the dbt map for pull request branches
          </label>
          <label className="flex items-center gap-2.5 text-xs text-[var(--color-text)]">
            <input
              type="checkbox"
              checked={prAgentTrigger}
              onChange={(event) => setPrAgentTrigger(event.target.checked)}
              className="h-3.5 w-3.5"
            />
            Trigger a SignalPilot agent run on pull requests
            <span className="rounded bg-[var(--color-bg-input)] px-1.5 py-0.5 text-[10px] text-[var(--color-text-dim)]">
              coming soon
            </span>
          </label>
        </div>

        {/* dbt map status + actions */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border)] pt-4">
          <div className="text-[11px] text-[var(--color-text-dim)]">
            dbt map:{" "}
            <span className="text-[var(--color-text)]">{mapStatus}</span>
            {mapInfo?.node_count ? ` · ${mapInfo.node_count} nodes` : ""}
            {mapInfo?.dbt_version ? ` · dbt ${mapInfo.dbt_version}` : ""}
            {mapStatus === "failed" && mapInfo?.error ? (
              <span className="block max-w-md truncate text-[var(--color-error)]">
                {mapInfo.error}
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void compileNow()}
              disabled={compiling}
              className="inline-flex items-center gap-1.5 rounded-[10px] border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text)] hover:border-[var(--color-text-dim)] disabled:opacity-50"
            >
              {compiling ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Hammer className="h-3.5 w-3.5" />
              )}
              Compile now
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-[10px] bg-[var(--color-text)] px-4 py-2 text-xs font-medium text-[var(--color-bg)] hover:opacity-90 disabled:opacity-50"
            >
              {saving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              Save
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
