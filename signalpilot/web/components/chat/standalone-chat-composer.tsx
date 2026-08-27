"use client";

import { AtSign, Send, Settings2, Square } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

const MAX_TEXTAREA_PX = 240;
const MENTION_RE = /(?:^|\s)@([\w./-]*)$/;

export function StandaloneChatComposer({
  value,
  onValueChange,
  onSubmit,
  submitDisabled,
  disabledReason,
  running,
  onStop,
  placeholder,
  projectPicker,
  mentionOptions,
  settings,
}: {
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: (value: string) => void;
  submitDisabled: boolean;
  /** Why submit is blocked — shown under the input instead of a silent no-op. */
  disabledReason?: string;
  /** A run is streaming: show the stop control. */
  running?: boolean;
  onStop?: () => void;
  placeholder: string;
  projectPicker?: ReactNode;
  /** Model/metric/table names for @-mention autocomplete. */
  mentionOptions?: string[];
  /** Optional settings popover content (budgets etc.), behind a gear. */
  settings?: ReactNode;
}) {
  const canSubmit = Boolean(value.trim()) && !submitDisabled;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [blockedFlash, setBlockedFlash] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);

  // Autosize: grow with content up to a cap, then scroll.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_PX)}px`;
  }, [value]);

  const mentionMatches = useMemo(() => {
    if (mentionQuery === null || !mentionOptions?.length) return [];
    const q = mentionQuery.toLowerCase();
    return mentionOptions
      .filter((m) => m.toLowerCase().includes(q))
      .slice(0, 8);
  }, [mentionQuery, mentionOptions]);

  const refreshMention = useCallback(
    (nextValue: string) => {
      const el = textareaRef.current;
      const caret = el ? el.selectionStart : nextValue.length;
      const before = nextValue.slice(0, caret ?? nextValue.length);
      const match = MENTION_RE.exec(before);
      setMentionQuery(match ? match[1] : null);
      setMentionIndex(0);
    },
    [],
  );

  const insertMention = useCallback(
    (name: string) => {
      const el = textareaRef.current;
      const caret = el ? el.selectionStart : value.length;
      const before = value.slice(0, caret ?? value.length);
      const after = value.slice(caret ?? value.length);
      const replaced = before.replace(MENTION_RE, (full) =>
        full.startsWith("@") ? `@${name} ` : `${full[0]}@${name} `,
      );
      onValueChange(replaced + after);
      setMentionQuery(null);
      requestAnimationFrame(() => {
        el?.focus();
        el?.setSelectionRange(replaced.length, replaced.length);
      });
    },
    [onValueChange, value],
  );

  const submit = useCallback(() => {
    const text = value.trim();
    if (!text) return;
    if (submitDisabled) {
      // Never a silent no-op: pulse the reason line.
      setBlockedFlash(true);
      setTimeout(() => setBlockedFlash(false), 1200);
      return;
    }
    onValueChange("");
    setMentionQuery(null);
    onSubmit(text);
  }, [onSubmit, onValueChange, submitDisabled, value]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionMatches.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setMentionIndex((i) => (i + 1) % mentionMatches.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setMentionIndex((i) => (i - 1 + mentionMatches.length) % mentionMatches.length);
        return;
      }
      if (event.key === "Tab" || event.key === "Enter") {
        event.preventDefault();
        insertMention(mentionMatches[mentionIndex]);
        return;
      }
      if (event.key === "Escape") {
        setMentionQuery(null);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div
      data-testid="standalone-chat-composer"
      className="mx-auto w-full max-w-3xl px-6 pb-6 pt-3"
    >
      {/* Single field: textarea on top, one borderless control bar beneath.
          A lifted surface (#1f1f22) separates it from the near-black page, so
          the border can stay soft — legibility over harsh outlines. */}
      <div className="relative flex flex-col rounded-2xl border border-[var(--color-border)] bg-[#1f1f22] shadow-2xl shadow-black/40 transition-colors focus-within:border-[var(--color-border-hover)]">
        {/* @-mention popover */}
        {mentionMatches.length > 0 && (
          <div className="absolute bottom-full left-4 z-30 mb-2 w-80 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-xl">
            <div className="flex items-center gap-1.5 border-b border-[var(--color-border)] px-3 py-1.5 text-[10px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]">
              <AtSign className="h-3 w-3" /> models &amp; metrics
            </div>
            {mentionMatches.map((name, i) => (
              <button
                key={name}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  insertMention(name);
                }}
                className={`block w-full truncate px-3 py-1.5 text-left font-mono text-xs ${
                  i === mentionIndex
                    ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                    : "text-[var(--color-text-muted)]"
                }`}
              >
                {name}
              </button>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          data-chat-composer
          rows={1}
          autoFocus
          value={value}
          onChange={(event) => {
            onValueChange(event.target.value);
            refreshMention(event.target.value);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          // The global stylesheet paints two rings on a focused textarea: a
          // `textarea:focus` box-shadow AND a `*:focus-visible` 1px outline
          // (drawn outside the box, so element screenshots hide it). Plain
          // Tailwind resets lose the specificity fight, so force both off with
          // !important — the OUTER container carries the focus affordance via
          // focus-within:border.
          // The global `::placeholder { opacity:.35 }` / `:focus::placeholder
          // { opacity:.25 }` rules crush the placeholder to near-invisible and
          // win on specificity — force full opacity + a legible muted color.
          className="min-h-[60px] w-full resize-none border-0 bg-transparent px-5 pb-1 pt-4 text-[16px] leading-7 text-[var(--color-text)] !shadow-none !outline-none placeholder:text-[var(--color-text-muted)] placeholder:!opacity-100 focus:!border-0 focus:!shadow-none focus:!outline-none focus:placeholder:!opacity-100 focus-visible:!outline-none focus-visible:!ring-0"
        />

        {/* Control bar: project picker (left), settings + send (right). */}
        <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
          {projectPicker && <div className="min-w-0 flex-1">{projectPicker}</div>}
          <div className="ml-auto flex items-center gap-1.5">
            {settings && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setSettingsOpen((v) => !v)}
                  aria-label="Chat settings"
                  aria-expanded={settingsOpen}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
                >
                  <Settings2 className="h-3.5 w-3.5" />
                </button>
                {settingsOpen && (
                  <div className="absolute bottom-10 right-0 z-30 w-64 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-3 shadow-xl">
                    {settings}
                  </div>
                )}
              </div>
            )}
            {running && onStop ? (
              <button
                type="button"
                onClick={onStop}
                aria-label="Stop the running analysis"
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--color-error)] text-[var(--color-error)] hover:bg-[var(--color-error)]/10"
              >
                <Square className="h-3 w-3 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                disabled={!canSubmit}
                onClick={submit}
                aria-label="Send message"
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-text)] text-[var(--color-bg)] transition-opacity disabled:cursor-not-allowed disabled:opacity-30"
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>

      {submitDisabled && disabledReason ? (
        <p
          aria-live="polite"
          className={`mt-2.5 text-center text-xs transition-colors ${
            blockedFlash ? "text-[var(--color-warning)]" : "text-[var(--color-text-muted)]"
          }`}
        >
          {disabledReason}
        </p>
      ) : (
        <p className="mt-2.5 text-center text-xs text-[var(--color-text-muted)]">
          Enter to send · Shift+Enter for a new line · @ to mention a model
        </p>
      )}
    </div>
  );
}
