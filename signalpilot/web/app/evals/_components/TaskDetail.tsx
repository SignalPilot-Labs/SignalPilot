"use client";

/** Slide-over panel with a task's writeup, prompt, grading spec, and capture settings. */

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { type EvalGrade, type EvalTask } from "~/lib/api";
import { Md } from "./Markdown";
import { ClassBadge } from "./badges";

/** The grading specification contains numeric checks or model_rebuilt expectations. */
function GradeSpec({ grade, checks }: { grade: EvalGrade | null; checks: EvalTask["checks"] }) {
  const rebuilt = grade?.kind === "model_rebuilt";
  const expectations = rebuilt && Array.isArray(grade?.expectations) ? grade.expectations : null;
  return (
    <div>
      <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">
        Grading{rebuilt ? " — model rebuilt" : " — gold checks"}
      </h3>
      {rebuilt && (
        <p className="text-xs text-[var(--color-text-muted)] mb-2">
          The agent must rebuild the model on its branch; grading verifies the rebuilt model
          against these expectations.
        </p>
      )}
      <table className="w-full text-left border-collapse text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)]">
            <th className="py-1 pr-4 font-normal">{rebuilt ? "expectation" : "check"}</th>
            <th className="py-1 pr-4 font-normal">gold value</th>
            <th className="py-1 font-normal">tolerance</th>
          </tr>
        </thead>
        <tbody>
          {(expectations ?? checks).length ? (
            (expectations ?? checks).map((c) => (
              <tr key={c.name} className="border-t border-[var(--color-border)]">
                <td className="py-1.5 pr-4 font-mono text-xs text-[var(--color-text-muted)]">{c.name}</td>
                <td className="py-1.5 pr-4 font-mono text-xs text-[var(--color-text)]">{c.value != null ? c.value.toLocaleString() : "—"}</td>
                <td className="py-1.5 font-mono text-xs text-[var(--color-text-muted)]">{c.tolerance != null ? `±${Math.round(c.tolerance * 100)}%` : "—"}</td>
              </tr>
            ))
          ) : (
            <tr className="border-t border-[var(--color-border)]">
              <td colSpan={3} className="py-1.5 text-xs text-[var(--color-text-dim)]">
                {rebuilt ? "graded on the model rebuild itself" : "ungraded — no numeric gold"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ChipList({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">{label}</h3>
      <div className="flex gap-1.5 flex-wrap">
        {items.map((m) => (
          <span key={m} className="ev-chip"><span className="font-mono">{m}</span></span>
        ))}
      </div>
    </div>
  );
}

export function TaskDetail({ t, onClose }: { t: EvalTask; onClose: () => void }) {
  // The animate-fade-in class leaves a transform on the page shell.
  // Render the panel in document.body to use the viewport as its containing block.
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
  useEffect(() => setPortalTarget(document.body), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!portalTarget) return null;

  return createPortal(
    <>
      <div className="ev-overlay" onClick={onClose} />
      <div className="ev-panel">
        <div className="sticky top-0 bg-[var(--color-bg-card)] border-b border-[var(--color-border)] px-6 py-4 flex items-center justify-between">
          <div>
            <code className="text-xs text-[var(--color-text-dim)]">{t.id}</code>
            <div className="flex items-center gap-1.5 mt-1">
              <ClassBadge cls={t.class} />
              <span className="ev-badge">{t.kind}</span>
              {t.grade?.kind === "model_rebuilt" && <span className="ev-badge">rebuild</span>}
            </div>
          </div>
          <button onClick={onClose} aria-label="close" className="text-[var(--color-text-dim)] hover:text-[var(--color-text)]">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-6 py-5 space-y-6">
          {t.doc ? (
            <Md>{t.doc}</Md>
          ) : (
            <p className="text-sm text-[var(--color-text-dim)]">
              No writeup — add <code>docs/{t.id}.md</code> to the eval repo (see eval-format.md).
            </p>
          )}

          <div>
            <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">Prompt sent to the agent</h3>
            <pre className="ev-raw border border-[var(--color-border)] rounded-[10px] bg-[var(--color-bg)] p-3">{t.prompt}</pre>
          </div>

          <GradeSpec grade={t.grade} checks={t.checks} />

          <ChipList label="Covers — models this task exercises" items={t.covers} />
          <ChipList label="Builds — models the agent must build" items={t.builds} />

          {t.capture && (
            <div>
              <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">Capture</h3>
              <div className="flex items-center gap-1.5 flex-wrap text-xs text-[var(--color-text-muted)]">
                {t.capture.tables.map((tb) => (
                  <span key={tb} className="ev-chip"><span className="font-mono">{tb}</span></span>
                ))}
                <span className="ev-badge">mode · {t.capture.mode}</span>
                <span className="ev-badge">{t.capture.sample_rows} sample rows</span>
              </div>
            </div>
          )}

          {(t.setup || t.teardown) && (
            <div>
              <h3 className="text-[11px] uppercase tracking-[0.08em] text-[var(--color-text-dim)] mb-2">Setup / teardown</h3>
              <div className="space-y-1 text-xs font-mono text-[var(--color-text-muted)]">
                {t.setup && <p><span className="text-[var(--color-text-dim)]">setup ·</span> {t.setup}</p>}
                {t.teardown && <p><span className="text-[var(--color-text-dim)]">teardown ·</span> {t.teardown}</p>}
              </div>
            </div>
          )}
        </div>
      </div>
    </>,
    portalTarget,
  );
}
