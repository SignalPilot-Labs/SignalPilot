import {
  CheckCircle2Icon,
  ClipboardCopyIcon,
  CodeIcon,
  EyeIcon,
  Loader2Icon,
  ScrollTextIcon,
  XCircleIcon,
} from "lucide-react";
import React, { Suspense } from "react";
import { Button } from "@/components/ui/button";
import { copyToClipboard } from "@/utils/copy";
import { cn } from "@/utils/cn";
import { useTheme } from "@/theme/useTheme";
import { darkTheme } from "@/core/codemirror/theme/dark";
import { lightTheme } from "@/core/codemirror/theme/light";
import { lineNumbers } from "@codemirror/view";
import { LazyAnyLanguageCodeMirror } from "@/plugins/impl/code/LazyAnyLanguageCodeMirror";
import type { DbtConsoleTab, DbtLogEntry, DbtPreviewModelResponse } from "./types";

interface DbtConsolePanelProps {
  activeTab: DbtConsoleTab;
  onTabChange: (tab: DbtConsoleTab) => void;
  compiledSql: string;
  previewResults: DbtPreviewModelResponse | null;
  logs: DbtLogEntry[];
  isCompiling: boolean;
  isPreviewing: boolean;
  onCompile?: () => void;
  onPreview?: () => void;
}

export const DbtConsolePanel: React.FC<DbtConsolePanelProps> = ({
  activeTab,
  onTabChange,
  compiledSql,
  previewResults,
  logs,
  isCompiling,
  isPreviewing,
  onCompile,
  onPreview,
}) => {
  const tabs: { id: DbtConsoleTab; label: string; icon: React.ReactNode }[] = [
    { id: "results", label: "Results", icon: <EyeIcon size={12} /> },
    { id: "compiled", label: "Compiled", icon: <CodeIcon size={12} /> },
    { id: "logs", label: "Logs", icon: <ScrollTextIcon size={12} /> },
  ];

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Tab bar */}
      <div className="flex items-center border-b border-border px-2 shrink-0">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wider transition-colors border-b-2 -mb-px cursor-pointer",
              activeTab === tab.id
                ? "text-foreground border-emerald-500"
                : "text-muted-foreground border-transparent hover:text-foreground hover:border-border",
            )}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.icon}
            {tab.label}
            {tab.id === "results" && isPreviewing && (
              <Loader2Icon size={10} className="animate-spin" />
            )}
            {tab.id === "compiled" && isCompiling && (
              <Loader2Icon size={10} className="animate-spin" />
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto">
        {activeTab === "results" && (
          <ResultsTab results={previewResults} isLoading={isPreviewing} onPreview={onPreview} />
        )}
        {activeTab === "compiled" && (
          <CompiledTab sql={compiledSql} isLoading={isCompiling} onCompile={onCompile} />
        )}
        {activeTab === "logs" && <LogsTab logs={logs} />}
      </div>
    </div>
  );
};

// ── Results Tab ──────────────────────────────────────────────────

const ResultsTab: React.FC<{
  results: DbtPreviewModelResponse | null;
  isLoading: boolean;
  onPreview?: () => void;
}> = ({ results, isLoading, onPreview }) => {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground gap-2">
        <Loader2Icon size={16} className="animate-spin" />
        Running preview...
      </div>
    );
  }

  if (!results) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <EyeIcon size={24} className="opacity-30" />
        <span className="text-xs">No results yet</span>
        {onPreview && (
          <Button variant="outline" size="sm" className="gap-1.5 text-xs" onClick={onPreview}>
            <EyeIcon size={12} />
            Preview this model
          </Button>
        )}
      </div>
    );
  }

  if (!results.success) {
    return (
      <div className="p-4">
        <div className="flex items-center gap-2 text-destructive text-sm mb-2">
          <XCircleIcon size={14} />
          Preview failed
        </div>
        <pre className="text-xs font-mono whitespace-pre-wrap bg-destructive/10 rounded p-3 text-destructive">
          {results.error}
        </pre>
      </div>
    );
  }

  if (results.columns.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-xs">
        No results returned
      </div>
    );
  }

  return (
    <div className="overflow-auto h-full">
      <div className="px-3 py-1.5 text-[10px] text-muted-foreground border-b border-border">
        {results.rowCount} row{results.rowCount !== 1 ? "s" : ""} &middot;{" "}
        {results.columns.length} column{results.columns.length !== 1 ? "s" : ""}
      </div>
      <table className="w-full text-xs font-mono">
        <thead className="sticky top-0 bg-background">
          <tr className="border-b border-border">
            {results.columns.map((col, i) => (
              <th
                key={i}
                className="text-left px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
              >
                {col.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {results.rows.map((row, i) => (
            <tr
              key={i}
              className="border-b border-border/50 hover:bg-muted/30 transition-colors"
            >
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-1 text-xs">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// ── Compiled Tab ─────────────────────────────────────────────────

const CompiledTab: React.FC<{
  sql: string;
  isLoading: boolean;
  onCompile?: () => void;
}> = ({ sql, isLoading, onCompile }) => {
  const { theme } = useTheme();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground gap-2">
        <Loader2Icon size={16} className="animate-spin" />
        Compiling...
      </div>
    );
  }

  if (!sql) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
        <CodeIcon size={24} className="opacity-30" />
        <span className="text-xs">Nothing compiled yet</span>
        {onCompile && (
          <Button variant="outline" size="sm" className="gap-1.5 text-xs" onClick={onCompile}>
            <CodeIcon size={12} />
            Compile this model
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-1 border-b border-border">
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
          Compiled SQL
        </span>
        <Button
          variant="text"
          size="xs"
          className="text-[10px] gap-1"
          onClick={() => copyToClipboard(sql)}
        >
          <ClipboardCopyIcon size={10} />
          Copy
        </Button>
      </div>
      <div className="flex-1 overflow-auto">
        <Suspense>
          <LazyAnyLanguageCodeMirror
            theme="dark"
            language="sql"
            extensions={[
              ...(theme === "dark" ? darkTheme : lightTheme),
              lineNumbers(),
            ]}
            value={sql}
            readOnly={true}
            editable={false}
          />
        </Suspense>
      </div>
    </div>
  );
};

// ── Logs Tab ─────────────────────────────────────────────────────

const LogsTab: React.FC<{ logs: DbtLogEntry[] }> = ({ logs }) => {
  if (logs.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-xs">
        No commands run yet
      </div>
    );
  }

  return (
    <div className="overflow-auto h-full">
      {logs.map((entry) => (
        <LogEntry key={entry.id} entry={entry} />
      ))}
    </div>
  );
};

const LogEntry: React.FC<{ entry: DbtLogEntry }> = ({ entry }) => {
  const [expanded, setExpanded] = React.useState(true);
  const duration = (entry.durationMs / 1000).toFixed(1);

  return (
    <div className="border-b border-border/50">
      <button
        type="button"
        className={cn(
          "w-full flex items-center gap-1.5 px-3 py-1.5 text-xs hover:bg-muted/30 transition-colors cursor-pointer",
          !entry.success && "text-destructive",
        )}
        onClick={() => setExpanded(!expanded)}
      >
        {entry.success ? (
          <CheckCircle2Icon size={11} className="text-emerald-500 shrink-0" />
        ) : (
          <XCircleIcon size={11} className="shrink-0" />
        )}
        <code className="font-mono text-[11px] truncate flex-1 text-left">
          {entry.command}
        </code>
        <span className="text-[10px] text-muted-foreground shrink-0">
          {duration}s
        </span>
      </button>
      {expanded && (entry.stdout || entry.stderr) && (
        <div className="px-3 pb-2">
          {entry.stdout && (
            <pre className="text-[10px] font-mono whitespace-pre-wrap bg-muted/20 rounded p-2 max-h-[200px] overflow-auto">
              {entry.stdout}
            </pre>
          )}
          {entry.stderr && (
            <pre className="text-[10px] font-mono whitespace-pre-wrap bg-destructive/10 text-destructive rounded p-2 mt-1 max-h-[150px] overflow-auto">
              {entry.stderr}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};
