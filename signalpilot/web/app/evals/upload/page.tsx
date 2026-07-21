"use client";

/**
 * Hidden eval-upload page (/evals/upload) — not linked from the sidebar.
 * Spec: eval-upload-spec.md §2. Three states: ready → uploading → done.
 * Backend: POST /api/evals/upload (gateway/api/uploads.py).
 */

import { useCallback, useRef, useState } from "react";
import {
  CheckCircle2,
  FileArchive,
  Lock,
  UploadCloud,
  X,
} from "lucide-react";
import { uploadEval, type EvalUploadResult } from "~/lib/api";
import { PageHeader } from "~/components/ui/page-header";

const MAX_MB = 500;

type Phase =
  | { state: "ready" }
  | { state: "uploading"; pct: number }
  | { state: "done"; result: EvalUploadResult };

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

function validate(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".zip")) {
    return `"${file.name}" isn't a .zip file — please zip your eval materials first.`;
  }
  if (file.size > MAX_MB * 1024 * 1024) {
    return `That file is ${Math.round(file.size / (1024 * 1024))} MB — the limit is ${MAX_MB} MB. Try excluding data files, or reach out to us.`;
  }
  return null;
}

export default function EvalUploadPage() {
  const [phase, setPhase] = useState<Phase>({ state: "ready" });
  const [file, setFile] = useState<File | null>(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const pickFile = useCallback((f: File | undefined) => {
    if (!f) return;
    const problem = validate(f);
    setError(problem);
    setFile(problem ? null : f);
  }, []);

  async function startUpload() {
    if (!file) return;
    setError(null);
    setPhase({ state: "uploading", pct: 0 });
    const guard = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", guard);
    try {
      const result = await uploadEval(file, notes, (pct) =>
        setPhase({ state: "uploading", pct }),
      );
      setPhase({ state: "done", result });
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 413 || status === 415) {
        setError((err as Error).message);
      } else {
        setError("Something went wrong on our end — try again, and email us if it persists.");
      }
      setPhase({ state: "ready" });
    } finally {
      window.removeEventListener("beforeunload", guard);
    }
  }

  function reset() {
    setPhase({ state: "ready" });
    setFile(null);
    setNotes("");
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="min-h-screen p-8 animate-fade-in">
      <PageHeader
        title="eval upload"
        subtitle="share"
        description="send your eval materials to the SignalPilot team"
      />

      <div className="max-w-xl mx-auto mt-8 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-8">
        {phase.state === "done" ? (
          <div className="flex flex-col items-center text-center gap-4 py-6">
            <CheckCircle2 className="w-10 h-10 text-[var(--color-success)]" strokeWidth={1.25} />
            <div>
              <p className="text-[var(--color-text)] text-lg font-light">
                Uploaded — the team has been notified.
              </p>
              <p className="mt-3 text-sm text-[var(--color-text-muted)]">
                Reference ID:{" "}
                <code className="text-[var(--color-text)] tracking-wider">
                  {phase.result.reference_id}
                </code>
              </p>
              <p className="mt-1 text-sm text-[var(--color-text-muted)]">
                Your file is deleted automatically on {phase.result.expires_at}.
              </p>
            </div>
            <button
              onClick={reset}
              className="mt-2 px-4 py-2 text-sm border border-[var(--color-border)] text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors"
            >
              Upload another
            </button>
          </div>
        ) : (
          <>
            <h2 className="text-[var(--color-text)] font-light tracking-wide mb-5">
              Share your eval with the SignalPilot team
            </h2>

            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                if (phase.state === "ready") pickFile(e.dataTransfer.files?.[0]);
              }}
              onClick={() => phase.state === "ready" && inputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
              className={`border border-dashed px-6 py-8 text-center cursor-pointer transition-colors ${
                dragOver
                  ? "border-[var(--color-success)] bg-[var(--color-bg)]"
                  : "border-[var(--color-border-hover)] hover:border-[var(--color-text-dim)]"
              }`}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={(e) => pickFile(e.target.files?.[0])}
              />
              {file ? (
                <div className="flex items-center justify-center gap-3 text-[var(--color-text)]">
                  <FileArchive className="w-5 h-5 flex-shrink-0" strokeWidth={1.5} />
                  <span className="text-sm truncate">{file.name}</span>
                  <span className="text-xs text-[var(--color-text-muted)]">{formatSize(file.size)}</span>
                  {phase.state === "ready" && (
                    <button
                      onClick={(e) => { e.stopPropagation(); setFile(null); if (inputRef.current) inputRef.current.value = ""; }}
                      aria-label="remove file"
                      className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2 text-[var(--color-text-muted)]">
                  <UploadCloud className="w-7 h-7 text-[var(--color-text-dim)]" strokeWidth={1.25} />
                  <p className="text-sm">Drag a .zip here or click to browse</p>
                  <p className="text-xs text-[var(--color-text-dim)]">Max {MAX_MB} MB · .zip only</p>
                </div>
              )}
            </div>

            {error && (
              <p className="mt-3 text-sm text-[var(--color-error,#e5484d)]">{error}</p>
            )}

            {/* Notes */}
            <label className="block mt-5 text-xs uppercase tracking-[0.15em] text-[var(--color-text-muted)]">
              Notes for the team (optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 2000))}
              disabled={phase.state === "uploading"}
              placeholder='e.g. "Snowflake dialect, see README inside for setup"'
              rows={3}
              className="mt-2 w-full bg-transparent border border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-dim)] focus:border-[var(--color-border-hover)] focus:outline-none resize-none"
            />

            {/* Upload button / progress */}
            {phase.state === "uploading" ? (
              <div className="mt-5">
                <div className="h-8 border border-[var(--color-border)] relative overflow-hidden">
                  <div
                    className="absolute inset-y-0 left-0 bg-[var(--color-success)] opacity-25 transition-[width] duration-200"
                    style={{ width: `${phase.pct}%` }}
                  />
                  <div className="absolute inset-0 flex items-center justify-center text-xs tracking-wider text-[var(--color-text)]">
                    Uploading… {phase.pct}%
                  </div>
                </div>
              </div>
            ) : (
              <button
                onClick={startUpload}
                disabled={!file}
                className="mt-5 w-full py-2.5 text-sm tracking-wide border border-[var(--color-border-hover)] text-[var(--color-text)] hover:bg-[var(--color-bg)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Upload eval
              </button>
            )}

            <p className="mt-5 flex items-start gap-2 text-xs leading-relaxed text-[var(--color-text-muted)]">
              <Lock className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[var(--color-text-dim)]" strokeWidth={1.5} />
              Stored encrypted, visible only to the SignalPilot team, and automatically
              deleted after 7 days.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
