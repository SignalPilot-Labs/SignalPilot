import {
  AlertCircleIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  DatabaseIcon,
  FolderOpenIcon,
  Loader2Icon,
  PlayIcon,
  RefreshCwIcon,
  XCircleIcon,
} from "lucide-react";
import { useAtomValue } from "jotai";
import React, { useEffect, useState } from "react";
import { ClearButton } from "@/components/buttons/clear-button";
import { Button } from "@/components/ui/button";
import { isConnectedAtom } from "@/core/network/connection";
import { cn } from "@/utils/cn";
import { copyToClipboard } from "@/utils/copy";
import { PanelEmptyState } from "../chrome/panels/empty-state";
import type { DbtLogEntry, DbtProjectInfo } from "./types";
import {
  useDbtActions,
  useDbtLogs,
  useDbtProjectInfo,
  useDbtStatus,
} from "./use-dbt";

const DbtPanel: React.FC = () => {
  const logs = useDbtLogs();
  const status = useDbtStatus();
  const projectInfo = useDbtProjectInfo();
  const connected = useAtomValue(isConnectedAtom);
  const { runCommand, refreshProjectInfo, clearLogs } = useDbtActions();

  // Detect dbt project when the panel opens. Skips if already detected
  // (pre-fetched by edit-app after sync-down). Retries with backoff if
  // the kernel isn't ready yet.
  useEffect(() => {
    if (projectInfo?.found) return;
    if (!connected) return;
    let cancelled = false;

    async function detectWithRetry() {
      for (let attempt = 0; attempt < 5 && !cancelled; attempt++) {
        const info = await refreshProjectInfo();
        if (info?.found || cancelled) return;
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
      }
    }

    detectWithRetry();
    return () => { cancelled = true; };
  }, [connected, projectInfo?.found, refreshProjectInfo]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Project setup section */}
      <DbtProjectSetup
        projectInfo={projectInfo}
        onRefresh={refreshProjectInfo}
      />

      {/* Command bar - only show when project is connected */}
      {projectInfo?.found && (
        <div className="px-2 py-2 border-b">
          <DbtCommandBar status={status} onRunCommand={runCommand} />
        </div>
      )}

      {/* Log entries */}
      {logs.length === 0 ? (
        <PanelEmptyState
          title={projectInfo?.found ? "No dbt output" : "No dbt project"}
          description={
            projectInfo?.found
              ? "Run a dbt command to see output here."
              : "Set your dbt project directory above to get started."
          }
          icon={<DatabaseIcon />}
        />
      ) : (
        <div className="flex-1 overflow-auto">
          <div className="flex flex-row justify-start px-2 py-1">
            <ClearButton dataTestId="clear-dbt-logs" onClick={clearLogs} />
          </div>
          {logs.map((entry) => (
            <DbtLogEntryView key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
};

export default DbtPanel;

// ─── Project Setup ───────────────────────────────────────────────

interface DbtProjectSetupProps {
  projectInfo: DbtProjectInfo | null;
  onRefresh: (dir?: string) => Promise<DbtProjectInfo | null>;
}

const DbtProjectSetup: React.FC<DbtProjectSetupProps> = ({
  projectInfo,
  onRefresh,
}) => {
  const { projectDir, setProjectDir } = useDbtActions();
  const [inputDir, setInputDir] = useState(projectDir || "");
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(!projectInfo?.found);

  useEffect(() => {
    if (projectDir) {
      setInputDir(projectDir);
    }
  }, [projectDir]);

  useEffect(() => {
    setExpanded(!projectInfo?.found);
  }, [projectInfo?.found]);

  const handleConnect = async () => {
    setLoading(true);
    const dir = inputDir.trim() || undefined;
    if (dir) {
      setProjectDir(dir);
    }
    await onRefresh(dir);
    setLoading(false);
  };

  return (
    <div className="border-b">
      {/* Header - always visible */}
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-muted/50 transition-colors cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDownIcon size={12} />
        ) : (
          <ChevronRightIcon size={12} />
        )}
        <DatabaseIcon size={12} />
        {projectInfo?.found ? (
          <span className="flex items-center gap-1.5 flex-1 text-left">
            <CheckCircle2Icon
              size={10}
              className="text-green-600 dark:text-green-400 shrink-0"
            />
            <span className="font-medium truncate">
              {projectInfo.projectName || "dbt project"}
            </span>
            {projectInfo.dbtVersion && (
              <span className="text-muted-foreground">
                v{projectInfo.dbtVersion}
              </span>
            )}
          </span>
        ) : (
          <span className="flex items-center gap-1.5 flex-1 text-left">
            <AlertCircleIcon
              size={10}
              className="text-amber-500 shrink-0"
            />
            <span className="text-muted-foreground">
              No project connected
            </span>
          </span>
        )}
      </button>

      {/* Expanded setup form */}
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {/* Directory input */}
          <div className="space-y-1">
            <label className="text-[10px] uppercase tracking-wide text-muted-foreground font-semibold">
              Project directory
            </label>
            <div className="flex gap-1">
              <div className="relative flex-1">
                <FolderOpenIcon
                  size={12}
                  className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
                />
                <input
                  type="text"
                  className="w-full text-[11px] font-mono bg-muted/50 rounded pl-6 pr-2 py-1.5 border border-border focus:outline-none focus:ring-1 focus:ring-ring"
                  placeholder="/path/to/dbt/project"
                  value={inputDir}
                  onChange={(e) => setInputDir(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleConnect();
                    }
                  }}
                />
              </div>
              <Button
                variant="outline"
                size="xs"
                className="h-7 px-2 text-[10px]"
                onClick={handleConnect}
                disabled={loading}
              >
                {loading ? (
                  <Loader2Icon size={10} className="animate-spin" />
                ) : (
                  <RefreshCwIcon size={10} />
                )}
                {projectInfo?.found ? "Refresh" : "Connect"}
              </Button>
            </div>
            <p className="text-[10px] text-muted-foreground">
              Path to folder containing{" "}
              <code className="text-[10px] bg-muted rounded px-0.5">
                dbt_project.yml
              </code>
              . Leave empty to auto-detect from cwd.
            </p>
          </div>

          {/* Status details */}
          {projectInfo && (
            <div className="space-y-1">
              <StatusRow
                label="dbt installed"
                ok={projectInfo.dbtInstalled}
                detail={
                  projectInfo.dbtInstalled
                    ? projectInfo.dbtVersion
                      ? `v${projectInfo.dbtVersion}`
                      : "Yes"
                    : "pip install dbt-core"
                }
              />
              <StatusRow
                label="Project found"
                ok={projectInfo.found}
                detail={
                  projectInfo.found
                    ? projectInfo.projectDir || ""
                    : "No dbt_project.yml found"
                }
              />
              {projectInfo.found && (
                <>
                  <StatusRow
                    label="Profile configured"
                    ok={projectInfo.hasProfiles}
                    detail={
                      projectInfo.hasProfiles
                        ? projectInfo.profile || "Yes"
                        : "Run: dbt debug"
                    }
                  />
                  <StatusRow
                    label="Manifest available"
                    ok={projectInfo.hasManifest}
                    detail={
                      projectInfo.hasManifest
                        ? "target/manifest.json"
                        : "Run: dbt parse"
                    }
                  />
                </>
              )}
            </div>
          )}

          {/* Quick start hints */}
          {!projectInfo?.found && (
            <div className="rounded bg-muted/50 p-2 space-y-1">
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                Quick start
              </p>
              <div className="text-[10px] text-muted-foreground space-y-0.5">
                <p>
                  1. Enter the path to an existing dbt project, or clone one:
                </p>
                <code className="block bg-muted rounded px-1 py-0.5 text-[10px]">
                  git clone https://github.com/dbt-labs/jaffle-shop
                </code>
                <p>2. Install dbt if needed:</p>
                <code className="block bg-muted rounded px-1 py-0.5 text-[10px]">
                  pip install dbt-core dbt-duckdb
                </code>
                <p>3. Click Connect, then run dbt debug to verify.</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const StatusRow: React.FC<{
  label: string;
  ok: boolean;
  detail?: string;
}> = ({ label, ok, detail }) => (
  <div className="flex items-center gap-1.5 text-[10px]">
    {ok ? (
      <CheckCircle2Icon
        size={10}
        className="text-green-600 dark:text-green-400 shrink-0"
      />
    ) : (
      <XCircleIcon
        size={10}
        className="text-red-500 dark:text-red-400 shrink-0"
      />
    )}
    <span className="font-medium">{label}</span>
    {detail && (
      <span className="text-muted-foreground truncate ml-auto">{detail}</span>
    )}
  </div>
);

// ─── Command Bar ─────────────────────────────────────────────────

const DBT_QUICK_COMMANDS = [
  { label: "run", command: "run", description: "Run models" },
  { label: "build", command: "build", description: "Build all" },
  { label: "compile", command: "compile", description: "Compile SQL" },
  { label: "test", command: "test", description: "Run tests" },
  { label: "deps", command: "deps", description: "Install packages" },
  { label: "debug", command: "debug", description: "Debug connection" },
  { label: "parse", command: "parse", description: "Parse project" },
  { label: "seed", command: "seed", description: "Load seeds" },
  { label: "ls", command: "ls", description: "List resources" },
] as const;

interface DbtCommandBarProps {
  status: string;
  onRunCommand: (command: string, args?: string[]) => Promise<unknown>;
}

const DbtCommandBar: React.FC<DbtCommandBarProps> = ({
  status,
  onRunCommand,
}) => {
  const [customArgs, setCustomArgs] = useState("");
  const isRunning = status === "running";

  return (
    <div className="flex flex-col gap-1">
      {/* Quick command buttons */}
      <div className="flex flex-wrap gap-1">
        {DBT_QUICK_COMMANDS.map(({ label, command, description }) => (
          <Button
            key={command}
            variant="outline"
            size="xs"
            className="text-[10px] h-5 px-1.5 font-mono"
            disabled={isRunning}
            onClick={() => {
              const args = customArgs.trim()
                ? customArgs.trim().split(/\s+/)
                : undefined;
              onRunCommand(command, args);
            }}
            title={description}
          >
            {isRunning ? (
              <Loader2Icon size={8} className="animate-spin mr-0.5" />
            ) : (
              <PlayIcon size={8} className="mr-0.5" />
            )}
            {label}
          </Button>
        ))}
      </div>

      {/* Custom args input */}
      <div className="flex gap-1 items-center">
        <input
          type="text"
          className="flex-1 text-[11px] font-mono bg-muted/50 rounded px-1.5 py-0.5 border border-border focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="--select model_name --full-refresh"
          value={customArgs}
          onChange={(e) => setCustomArgs(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !isRunning && customArgs.trim()) {
              const parts = customArgs.trim().split(/\s+/);
              const cmd = parts[0];
              const rest = parts.slice(1);
              if (DBT_QUICK_COMMANDS.some((c) => c.command === cmd)) {
                onRunCommand(cmd, rest.length > 0 ? rest : undefined);
              } else {
                onRunCommand("run", parts);
              }
            }
          }}
          disabled={isRunning}
        />
      </div>
    </div>
  );
};

// ─── Log Entry ───────────────────────────────────────────────────

interface DbtLogEntryViewProps {
  entry: DbtLogEntry;
}

const DbtLogEntryView: React.FC<DbtLogEntryViewProps> = ({ entry }) => {
  const [expanded, setExpanded] = useState(true);
  const timestamp = new Date(entry.timestamp).toLocaleTimeString();
  const duration = (entry.durationMs / 1000).toFixed(1);

  return (
    <div className="border-b last:border-b-0">
      {/* Header */}
      <button
        type="button"
        className={cn(
          "w-full flex items-center gap-1.5 px-2 py-1.5 text-xs hover:bg-muted/50 transition-colors cursor-pointer",
          !entry.success && "text-red-600 dark:text-red-400",
        )}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDownIcon size={12} className="shrink-0" />
        ) : (
          <ChevronRightIcon size={12} className="shrink-0" />
        )}
        {entry.success ? (
          <CheckCircle2Icon
            size={12}
            className="shrink-0 text-green-600 dark:text-green-400"
          />
        ) : (
          <XCircleIcon size={12} className="shrink-0" />
        )}
        <code className="font-mono text-[11px] truncate flex-1 text-left">
          {entry.command}
        </code>
        <span className="text-[10px] text-muted-foreground shrink-0">
          {duration}s
        </span>
        <span className="text-[10px] text-muted-foreground shrink-0">
          {timestamp}
        </span>
        <span
          role="button"
          tabIndex={0}
          className="p-0 h-4 opacity-50 hover:opacity-100 cursor-pointer inline-flex items-center"
          onClick={(e) => {
            e.stopPropagation();
            const text = entry.stdout || entry.stderr;
            copyToClipboard(text);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.stopPropagation();
              const text = entry.stdout || entry.stderr;
              copyToClipboard(text);
            }
          }}
        >
          <CopyIcon size={10} />
        </span>
      </button>

      {/* Output */}
      {expanded && (
        <div className="px-2 pb-2">
          {entry.stdout && (
            <pre className="text-[11px] font-mono whitespace-pre-wrap bg-muted/30 rounded p-2 max-h-[300px] overflow-auto">
              {entry.stdout}
            </pre>
          )}
          {entry.stderr && (
            <pre className="text-[11px] font-mono whitespace-pre-wrap bg-red-50 dark:bg-red-950/20 text-red-700 dark:text-red-300 rounded p-2 mt-1 max-h-[200px] overflow-auto">
              {entry.stderr}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};
