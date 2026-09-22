"use client";

import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { getDbtMap } from "~/lib/api";
import type { DbtMapInfo } from "~/lib/types";

const POLL_MS = 3000;

const PHASE_LABEL: Record<string, string> = {
  snapshot: "packaging the workspace",
  sandbox: "starting a sandbox",
  dbt: "running dbt deps + parse",
  store: "storing the lineage graph",
};

const TRIGGER_LABEL: Record<string, string> = {
  manual: "manual",
  push: "a push",
  pr: "a pull request",
  sync: "the repo sync",
  settings: "a settings change",
};

function isLive(status: string) {
  return status === "running" || status === "queued";
}

/** Latest compile state for a project's default branch, polled every few
 *  seconds while a compile is in flight so the page shows progress. */
export function useDbtMapStatus(projectId: string) {
  const [status, setStatus] = useState<string>("none");
  const [info, setInfo] = useState<DbtMapInfo | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getDbtMap(projectId, undefined, false);
      setStatus(res.status);
      setInfo(res.map);
      return res.status;
    } catch {
      return null;
    }
  }, [projectId]);

  const live = isLive(status);
  useEffect(() => {
    let active = true;
    const tick = async () => {
      const next = await refresh();
      if (!active) return;
      if (next && isLive(next)) timer.current = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
    // A live status re-arms the poll; a finished one lets it lapse.
  }, [refresh, live]);

  return { status, info, refresh };
}

function relative(seconds: number) {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

function dirLabel(dir: string | null | undefined) {
  if (dir === null || dir === undefined) return null;
  return dir === "" ? "repo root" : dir;
}

/** One line of compile state: what is happening now, or what last happened. */
export function DbtMapStatusLine({ status, info }: { status: string; info: DbtMapInfo | null }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    // Seconds tick while compiling; "N min ago" only needs a coarse clock.
    const id = setInterval(() => setNow(Date.now() / 1000), isLive(status) ? 1000 : 30000);
    return () => clearInterval(id);
  }, [status]);

  const dir = dirLabel(info?.dbt_project_dir);
  const trigger = info ? (TRIGGER_LABEL[info.trigger] ?? info.trigger) : null;

  if (!info || status === "none") {
    return <div className="text-[11px] text-[var(--color-text-dim)]">dbt map: not compiled yet</div>;
  }

  if (isLive(status)) {
    const phase = info.phase ? (PHASE_LABEL[info.phase] ?? info.phase) : "queued";
    return (
      <div className="flex items-center gap-2 text-[11px] text-[var(--color-text-dim)]">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-text)]" />
        <span>
          <span className="text-[var(--color-text)]">Compiling{dir ? ` ${dir}` : ""}</span>
          {` · ${phase} · ${relative(now - info.created_at)}`}
          {trigger ? ` · triggered by ${trigger}` : ""}
        </span>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="text-[11px] text-[var(--color-text-dim)]">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-3.5 w-3.5 text-[var(--color-error)]" />
          <span>
            <span className="text-[var(--color-error)]">Compile failed</span>
            {dir ? ` for ${dir}` : ""} · {relative(now - info.updated_at)} ago
            {trigger ? ` · triggered by ${trigger}` : ""}
          </span>
        </div>
        {info.error ? (
          <pre className="mt-1 max-h-32 max-w-xl overflow-auto whitespace-pre-wrap rounded bg-[var(--color-bg-input)] p-2 text-[10px] text-[var(--color-error)]">
            {info.error}
          </pre>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-[11px] text-[var(--color-text-dim)]">
      <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-success)]" />
      <span>
        <span className="text-[var(--color-text)]">Compiled{dir ? ` ${dir}` : ""}</span>
        {info.node_count ? ` · ${info.node_count} nodes` : ""}
        {info.dbt_version ? ` · dbt ${info.dbt_version}` : ""}
        {` · ${relative(now - info.updated_at)} ago`}
        {trigger ? ` · triggered by ${trigger}` : ""}
      </span>
    </div>
  );
}
