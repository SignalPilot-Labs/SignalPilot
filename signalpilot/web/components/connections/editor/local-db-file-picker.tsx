"use client";

import { useCallback, useState, type Ref } from "react";
import { ArrowLeft, FileText, Folder, HardDrive, Loader2 } from "lucide-react";

import { browseFiles } from "~/lib/api";

export function LocalDbFilePicker({ value, onChange, pattern = "*.duckdb", placeholder = "/path/to/database.duckdb", hint = "paste a file path or browse to select a file", id, inputRef, error }: { value: string; onChange: (v: string) => void; pattern?: string; placeholder?: string; hint?: string; id?: string; inputRef?: Ref<HTMLInputElement>; error?: string }) {
  const [browsing, setBrowsing] = useState(false);
  const [currentPath, setCurrentPath] = useState<string | null>(null);
  const [files, setFiles] = useState<{ name: string; path: string; size_bytes: number }[]>([]);
  const [directories, setDirectories] = useState<{ name: string; path: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);
  const browse = useCallback(async (path?: string) => {
    setLoading(true);
    setBrowseError(null);
    try {
      const data = await browseFiles(path, pattern);
      setCurrentPath(data.path);
      setFiles(data.files || []);
      setDirectories(data.directories || []);
      if (data.error) setBrowseError(data.error);
    } catch (e) {
      setBrowseError(e instanceof Error ? e.message : "Failed to browse files");
    } finally {
      setLoading(false);
    }
  }, []);
  const openBrowser = useCallback(() => {
    setBrowsing(true);
    browse();
  }, [browse]);
  const selectFile = useCallback((filePath: string) => {
    onChange(filePath);
    setBrowsing(false);
  }, [onChange]);
  const goUp = useCallback(() => {
    if (!currentPath) return;
    const parent = currentPath.split("/").slice(0, -1).join("/") || "/";
    browse(parent);
  }, [currentPath, browse]);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  };

  return (
    <div className="col-span-2">
      {/* Selected file display + browse button */}
      <label htmlFor={id} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">database file</label>
      <div className="flex gap-2">
        <input
          id={id}
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={error && id ? `${id}-error` : undefined}
          className={`flex-1 px-2.5 py-1.5 bg-[var(--color-bg-code)] border rounded-[10px] text-[13px] text-[var(--color-text)] font-mono focus:outline-none${error ? " border-[var(--color-error)]/60 focus:border-[var(--color-error)]" : " border-[var(--color-border)] focus:border-[var(--color-text-dim)]"}`}
        />
        <button
          type="button"
          onClick={openBrowser}
          className="px-3 py-1.5 text-[12px] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text-dim)] hover:border-[var(--color-text)] hover:text-[var(--color-text)] transition-colors duration-150 flex items-center gap-1.5"
        >
          <HardDrive size={13} />
          browse
        </button>
      </div>
      {error && id && <p id={`${id}-error`} role="alert" className="text-[11px] text-[var(--color-error)] mt-1">{error}</p>}
      {!error && (
        <p className="text-[11px] text-[var(--color-text-dim)] mt-1">
          {hint}
        </p>
      )}

      {/* File browser modal */}
      {browsing && (
        <div className="mt-2 border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg-code)] overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]/30">
            <button
              type="button"
              onClick={goUp}
              className="p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
              title="Go up"
            >
              <ArrowLeft size={14} />
            </button>
            <span className="text-[11px] text-[var(--color-text-muted)] font-mono truncate flex-1">
              {currentPath || "..."}
            </span>
            <button
              type="button"
              onClick={() => setBrowsing(false)}
              className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
            >
              close
            </button>
          </div>

          {/* Content */}
          <div className="max-h-[240px] overflow-y-auto">
            {loading && (
              <div className="flex items-center justify-center py-6">
                <Loader2 size={16} className="animate-spin text-[var(--color-text-dim)]" />
              </div>
            )}

            {browseError && (
              <div className="px-3 py-2 text-[11px] text-red-400">{browseError}</div>
            )}

            {!loading && !browseError && files.length === 0 && directories.length === 0 && (
              <div className="px-3 py-4 text-[11px] text-[var(--color-text-dim)] text-center">
                no matching files found in this directory
              </div>
            )}

            {!loading && directories.map((dir) => (
              <button
                key={dir.path}
                type="button"
                onClick={() => browse(dir.path)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-[var(--color-bg)]/50 transition-colors border-b border-[var(--color-border)]/30"
              >
                <Folder size={14} className="text-[var(--color-text-dim)] flex-shrink-0" />
                <span className="text-[12px] text-[var(--color-text-muted)] truncate">{dir.name}/</span>
              </button>
            ))}

            {!loading && files.map((file) => (
              <button
                key={file.path}
                type="button"
                onClick={() => selectFile(file.path)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-[var(--color-accent)]/10 transition-colors border-b border-[var(--color-border)]/30 group"
              >
                <FileText size={14} className="text-[var(--color-accent)] flex-shrink-0" />
                <span className="text-[12px] text-[var(--color-text)] truncate flex-1 group-hover:text-[var(--color-accent)]">
                  {file.name}
                </span>
                <span className="text-[10px] text-[var(--color-text-dim)] flex-shrink-0">
                  {formatSize(file.size_bytes)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
