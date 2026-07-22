"use client";

import { useEffect, useRef, useState } from "react";
import type { KnowledgeDoc, KnowledgeEdit } from "~/lib/types";
import { TimeAgo } from "~/components/ui/time-ago";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { KbIcon } from "./icons";

function renderDiff(before: string, after: string) {
  const beforeLines = before.split("\n");
  const afterLines = after.split("\n");
  const maxLen = Math.max(beforeLines.length, afterLines.length);
  const rows: { before: string | null; after: string | null }[] = [];
  for (let i = 0; i < maxLen; i++) {
    rows.push({
      before: i < beforeLines.length ? beforeLines[i] : null,
      after: i < afterLines.length ? afterLines[i] : null,
    });
  }
  return rows;
}

export function HistoryModal({
  doc,
  edits,
  onClose,
  onRevert,
}: {
  doc: KnowledgeDoc;
  edits: KnowledgeEdit[];
  onClose: () => void;
  onRevert: (edit: KnowledgeEdit) => void;
}) {
  const [diffEdit, setDiffEdit] = useState<KnowledgeEdit | null>(null);
  const [confirmRevert, setConfirmRevert] = useState<KnowledgeEdit | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  return (
    <div className="kb-modal-scrim !ml-0" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="edit history"
        className="kb-modal animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--kb-border)]">
          <span className="text-[13px] font-medium text-[var(--color-text)]">
            Edit history — <span className="text-[var(--color-text-muted)] font-normal">{doc.title}</span>
          </span>
          <button
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="close history"
            className="text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
          >
            <KbIcon name="close" size={16} />
          </button>
        </div>

        <div className="overflow-y-auto flex-1">
          {edits.length === 0 ? (
            <div className="px-5 py-8 text-center text-[12px] text-[var(--color-text-dim)]">no edit history</div>
          ) : (
            edits.map((edit) => {
              const byteDelta = doc.bytes - edit.bytes_before;
              const isDiffOpen = diffEdit?.id === edit.id;
              return (
                <div key={edit.id} className="border-b border-[var(--kb-border)] last:border-b-0">
                  <div className="flex items-center gap-3 px-5 py-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <TimeAgo timestamp={edit.edited_at} className="text-[12px] text-[var(--color-text-dim)] tabular-nums" />
                        <span className="kb-tag">{edit.edit_kind}</span>
                        {byteDelta !== 0 && (
                          <span className={`text-[11px] tabular-nums ${byteDelta > 0 ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                            {byteDelta > 0 ? "+" : ""}{byteDelta}B
                          </span>
                        )}
                        {edit.edited_by && (
                          <span className="text-[11px] text-[var(--color-text-dim)]">by {edit.edited_by}</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button onClick={() => setDiffEdit(isDiffOpen ? null : edit)} className="kb-btn kb-btn-sm">
                        {isDiffOpen ? "hide" : "diff"}
                      </button>
                      <button onClick={() => setConfirmRevert(edit)} className="kb-btn kb-btn-sm kb-btn-warn">
                        revert
                      </button>
                    </div>
                  </div>

                  {isDiffOpen && (
                    <div className="px-5 pb-3 animate-fade-in">
                      <div className="grid grid-cols-2 gap-2 text-[11px]">
                        <div>
                          <div className="px-2 py-1 rounded-md border border-[var(--kb-border)] bg-[var(--kb-surface-2)] mb-1 text-[var(--color-text-dim)] uppercase">before</div>
                          <div className="rounded-md border border-[var(--kb-border)] max-h-48 overflow-y-auto">
                            {renderDiff(edit.body_before, doc.body ?? "").map((row, i) => (
                              <div key={i} className={`px-2 py-0.5 font-mono whitespace-pre-wrap break-all leading-relaxed ${row.after === null ? "bg-[var(--color-error)]/10" : ""}`}>
                                {row.before ?? ""}
                              </div>
                            ))}
                          </div>
                        </div>
                        <div>
                          <div className="px-2 py-1 rounded-md border border-[var(--kb-border)] bg-[var(--kb-surface-2)] mb-1 text-[var(--color-text-dim)] uppercase">current</div>
                          <div className="rounded-md border border-[var(--kb-border)] max-h-48 overflow-y-auto">
                            {renderDiff(edit.body_before, doc.body ?? "").map((row, i) => (
                              <div key={i} className={`px-2 py-0.5 font-mono whitespace-pre-wrap break-all leading-relaxed ${row.before === null ? "bg-[var(--color-success)]/10" : ""}`}>
                                {row.after ?? ""}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmRevert !== null}
        title="revert document"
        message={`revert "${doc.title}" to this earlier version? the current body will be replaced.`}
        confirmLabel="revert"
        variant="danger"
        onConfirm={() => {
          if (confirmRevert) {
            onRevert(confirmRevert);
            setConfirmRevert(null);
            onClose();
          }
        }}
        onCancel={() => setConfirmRevert(null)}
      />
    </div>
  );
}
