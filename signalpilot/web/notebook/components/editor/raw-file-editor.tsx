import { apiCall } from "@/core/network/api-call";
import {
  bracketMatching,
  foldGutter,
  indentOnInput,
} from "@codemirror/language";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import { atom, useAtom, useAtomValue, useSetAtom } from "jotai";
import {
  CodeIcon,
  EyeIcon,
  FileIcon,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Suspense } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { toast } from "@/components/ui/use-toast";
import { cn } from "@/utils/cn";
import { darkTheme } from "@/core/codemirror/theme/dark";
import { lightTheme } from "@/core/codemirror/theme/light";
import { filenameAtom } from "@/core/saving/file-state";
import { useTheme } from "@/theme/useTheme";
import { LazyAnyLanguageCodeMirror } from "@/plugins/impl/code/LazyAnyLanguageCodeMirror";
import { MarkdownRenderer } from "@/components/markdown/markdown-renderer";
import { DbtConsolePanel } from "./dbt/dbt-console-panel";
import type { DbtPreviewModelResponse } from "./dbt/types";
import {
  compileModel,
  dbtConsoleTabAtom,
  getModelNameFromPath,
  isDbtModelFile,
  previewModel,
  useDbtLogs,
} from "./dbt/use-dbt";

const EXT_TO_LANGUAGE: Record<string, string> = {
  ".sql": "sql",
  ".yml": "yaml",
  ".yaml": "yaml",
  ".json": "json",
  ".toml": "toml",
  ".txt": "markdown",
  ".csv": "markdown",
  ".md": "markdown",
  ".py": "python",
  ".sh": "shell",
  ".bash": "shell",
  ".js": "javascript",
  ".ts": "javascript",
  ".html": "html",
  ".css": "css",
  ".xml": "xml",
  ".r": "r",
  ".cfg": "text",
  ".ini": "text",
  ".env": "text",
  ".gitignore": "text",
};

const EXT_TO_LABEL: Record<string, string> = {
  ".sql": "SQL",
  ".yml": "YAML",
  ".yaml": "YAML",
  ".json": "JSON",
  ".toml": "TOML",
  ".txt": "Text",
  ".csv": "CSV",
  ".md": "Markdown",
  ".py": "Python",
  ".sh": "Shell",
  ".bash": "Shell",
  ".js": "JavaScript",
  ".ts": "TypeScript",
  ".html": "HTML",
  ".css": "CSS",
  ".xml": "XML",
  ".r": "R",
  ".cfg": "Config",
  ".ini": "Config",
  ".env": "Env",
  ".gitignore": "Git",
};

// Shared atoms so Controls can trigger raw file save
export const rawFileNeedsSaveAtom = atom(false);
export const rawFileSaveFnAtom = atom<(() => void) | null>(null);

export function isRawFile(filename: string | null): boolean {
  if (!filename) {return false;}
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  return ext in EXT_TO_LANGUAGE;
}


async function fetchFileContents(path: string): Promise<string> {
  const data = await apiCall<{ contents?: string }>("/files/file_details", { path });
  return data.contents || "";
}

async function saveFileContents(
  path: string,
  contents: string,
): Promise<boolean> {
  const data = await apiCall<{ success: boolean }>("/files/update", { path, contents });
  return data.success;
}

interface RawFileEditorProps {
  filePath?: string;
}

export const RawFileEditor: React.FC<RawFileEditorProps> = ({ filePath }) => {
  const fallbackFilename = useAtomValue(filenameAtom);
  const filename = filePath || fallbackFilename;
  const { theme } = useTheme();
  const [value, setValue] = useState("");
  const [savedValue, setSavedValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [, setSaving] = useState(false);
  const [mdViewMode, setMdViewMode] = useState<"raw" | "rendered">("rendered");

  // dbt model state
  const isModel = filename ? isDbtModelFile(filename) : false;
  const modelName = filename ? getModelNameFromPath(filename) : null;
  const [consoleTab, setConsoleTab] = useAtom(dbtConsoleTabAtom);
  const [compiledSql, setCompiledSql] = useState("");
  const [previewResults, setPreviewResults] = useState<DbtPreviewModelResponse | null>(null);
  const [isCompiling, setIsCompiling] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const logs = useDbtLogs();

  const valueRef = useRef(value);
  valueRef.current = value;
  const savedValueRef = useRef(savedValue);
  savedValueRef.current = savedValue;
  const filenameRef = useRef(filename);
  filenameRef.current = filename;

  const ext = filename
    ? filename.slice(filename.lastIndexOf(".")).toLowerCase()
    : "";
  const language = EXT_TO_LANGUAGE[ext] || "text";
  const languageLabel = EXT_TO_LABEL[ext] || "File";
  const isDirty = value !== savedValue;

  // Expose save state to Controls
  const setRawNeedsSave = useSetAtom(rawFileNeedsSaveAtom);
  const setRawSaveFn = useSetAtom(rawFileSaveFnAtom);
  useEffect(() => {
    setRawNeedsSave(isDirty);
  }, [isDirty, setRawNeedsSave]);

  // Project context
  const projectDir = useMemo(() => {
    try {
      const raw = localStorage.getItem("sp:dbt-project-dir");
      if (raw && raw !== "null") return JSON.parse(raw) as string;
    } catch { /* ignore */ }
    return null;
  }, []);
  const projectName = projectDir?.split(/[/\\]/).pop() || null;
  const relativePath = projectDir && filename?.startsWith(projectDir)
    ? filename.slice(projectDir.length).replace(/^[/\\]/, "")
    : filename?.split(/[/\\]/).pop() || "Untitled";

  // Load file
  useEffect(() => {
    if (!filename) {return;}
    setLoading(true);
    setError(null);
    setCompiledSql("");
    setPreviewResults(null);
    fetchFileContents(filename)
      .then((contents) => {
        setValue(contents);
        setSavedValue(contents);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Failed to load file");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [filename]);

  // Save
  const doSave = useCallback(async () => {
    const currentFile = filenameRef.current;
    const currentValue = valueRef.current;
    const currentSaved = savedValueRef.current;
    if (!currentFile || currentValue === currentSaved) {return;}
    setSaving(true);
    try {
      const success = await saveFileContents(currentFile, currentValue);
      if (success) {
        setSavedValue(currentValue);
        toast({ title: "Saved", description: currentFile.split(/[/\\]/).pop() });
      }
    } catch (e) {
      toast({
        title: "Save failed",
        description: e instanceof Error ? e.message : "Unknown error",
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }, []);

  useEffect(() => {
    setRawSaveFn(() => doSave);
    return () => setRawSaveFn(null);
  }, [doSave, setRawSaveFn]);

  // Compile model
  const handleCompile = useCallback(async () => {
    if (!modelName) {return;}
    setIsCompiling(true);
    console.log("[dbt] Compiling model:", modelName, "projectDir:", projectDir);
    try {
      const result = await compileModel(modelName, projectDir);
      console.log("[dbt] Compile result:", { success: result.success, sqlLen: result.compiledSql?.length, error: result.error });
      if (result.success) {
        setCompiledSql(result.compiledSql);
        setConsoleTab("compiled");
      } else {
        setCompiledSql("");
        toast({ title: "Compile failed", description: result.error || "Unknown error", variant: "danger" });
      }
    } catch (e) {
      console.error("[dbt] Compile error:", e);
      toast({ title: "Compile failed", description: e instanceof Error ? e.message : "Unknown error", variant: "danger" });
    } finally {
      setIsCompiling(false);
    }
  }, [modelName, projectDir, setConsoleTab]);

  // Preview model
  const handlePreview = useCallback(async () => {
    if (!modelName) {return;}
    setIsPreviewing(true);
    console.log("[dbt] Previewing model:", modelName, "projectDir:", projectDir);
    try {
      const result = await previewModel(modelName, projectDir);
      console.log("[dbt] Preview result:", { success: result.success, cols: result.columns?.length, rows: result.rows?.length, error: result.error });
      setPreviewResults(result);
      setConsoleTab("results");
    } catch (e) {
      setPreviewResults({
        success: false,
        columns: [],
        rows: [],
        rowCount: 0,
        error: e instanceof Error ? e.message : "Unknown error",
      });
    } finally {
      setIsPreviewing(false);
    }
  }, [modelName, projectDir]);


  // Ctrl+S
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        doSave();
      }
    };
    window.addEventListener("keydown", handler, { capture: true });
    return () => window.removeEventListener("keydown", handler, { capture: true });
  }, [doSave]);

  // CodeMirror extensions
  const extensions = useMemo(() => {
    const themeExt = theme === "dark" ? darkTheme : lightTheme;
    return [
      ...themeExt,
      lineNumbers(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      foldGutter(),
      bracketMatching(),
      indentOnInput(),
      drawSelection(),
      highlightSelectionMatches(),
      EditorView.lineWrapping,
      keymap.of(searchKeymap),
    ];
  }, [theme]);

  const shortName = filename?.split(/[/\\]/).pop() || "Untitled";

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-foreground gap-4 p-8">
        <FileIcon size={48} className="text-muted-foreground" />
        <p className="text-destructive">{error}</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        Loading {shortName}...
      </div>
    );
  }

  // dbt model file → full IDE experience
  if (isModel && modelName) {
    return (
      <div className="flex flex-col h-full w-full overflow-hidden">
        <div className="flex items-center px-4 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            {projectName && (
              <>
                <span className="text-xs text-muted-foreground font-mono">
                  {projectName}
                </span>
                <span className="text-muted-foreground">/</span>
              </>
            )}
            <span className="text-sm font-mono font-medium truncate max-w-lg">
              {relativePath}
            </span>
            <span className="text-[10px] font-bold uppercase tracking-widest text-emerald-500 bg-emerald-500/10 px-2 py-0.5 rounded">
              MODEL
            </span>
            {isDirty && (
              <span className="text-[10px] font-bold uppercase tracking-widest text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded">
                Modified
              </span>
            )}
          </div>
        </div>
        <PanelGroup direction="vertical">
          <Panel defaultSize={60} minSize={20}>
            <div className="h-full overflow-auto">
              <Suspense>
                <LazyAnyLanguageCodeMirror
                  theme="dark"
                  language={language}
                  extensions={extensions}
                  value={value}
                  readOnly={false}
                  onChange={setValue}
                />
              </Suspense>
            </div>
          </Panel>
          <PanelResizeHandle className="group relative h-3 flex items-center justify-center cursor-row-resize bg-[#080808] hover:bg-[#111111] transition-colors border-y border-border">
            <div className="w-12 h-1 rounded-full bg-[#333333] group-hover:bg-[#555555] group-active:bg-emerald-500/50 transition-colors" />
          </PanelResizeHandle>
          <Panel defaultSize={40} minSize={10}>
            <DbtConsolePanel
              activeTab={consoleTab}
              onTabChange={setConsoleTab}
              compiledSql={compiledSql}
              previewResults={previewResults}
              logs={logs}
              isCompiling={isCompiling}
              isPreviewing={isPreviewing}
              onCompile={handleCompile}
              onPreview={handlePreview}
            />
          </Panel>
        </PanelGroup>
      </div>
    );
  }

  // Generic raw file → simple editor (with markdown preview toggle)
  const isMarkdown = language === "markdown" && ext === ".md";

  return (
    <div className="flex flex-col h-full w-full overflow-hidden">
      <div className="flex items-center justify-between px-4 py-4 border-b border-border shrink-0">
        <div className="flex items-center gap-3">
          {projectName && (
            <>
              <span className="text-xs text-muted-foreground font-mono">
                {projectName}
              </span>
              <span className="text-muted-foreground">/</span>
            </>
          )}
          <span className="text-sm font-mono font-medium truncate max-w-lg">
            {relativePath}
          </span>
          <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground bg-muted px-2 py-0.5 rounded">
            {languageLabel}
          </span>
          {isDirty && (
            <span className="text-[10px] font-bold uppercase tracking-widest text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded">
              Modified
            </span>
          )}
        </div>
      </div>
      {isMarkdown && (
        <div className="flex items-center gap-0 border-b border-border shrink-0 bg-[#080808] px-4">
          <button
            type="button"
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors border-b-2 -mb-px",
              mdViewMode === "rendered"
                ? "text-foreground border-emerald-500"
                : "text-muted-foreground border-transparent hover:text-foreground",
            )}
            onClick={() => setMdViewMode("rendered")}
          >
            <EyeIcon size={12} />
            Preview
          </button>
          <button
            type="button"
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors border-b-2 -mb-px",
              mdViewMode === "raw"
                ? "text-foreground border-emerald-500"
                : "text-muted-foreground border-transparent hover:text-foreground",
            )}
            onClick={() => setMdViewMode("raw")}
          >
            <CodeIcon size={12} />
            Raw
          </button>
        </div>
      )}
      <div className="flex-1 overflow-auto">
        {isMarkdown && mdViewMode === "rendered" ? (
          <div className="max-w-4xl mx-auto px-8 py-6 prose prose-invert prose-sm max-w-none">
            <MarkdownRenderer content={value} />
          </div>
        ) : (
          <div className="max-w-4xl mx-auto px-6 py-4">
            <div className="border border-border rounded-lg overflow-hidden shadow-sm">
              <Suspense>
                <LazyAnyLanguageCodeMirror
                  theme="dark"
                  language={language}
                  extensions={extensions}
                  value={value}
                  readOnly={false}
                  onChange={setValue}
                />
              </Suspense>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
