"use client";

import { Send } from "lucide-react";
import { useCallback, type KeyboardEvent, type ReactNode } from "react";

export function StandaloneChatComposer({
  value,
  onValueChange,
  onSubmit,
  submitDisabled,
  placeholder,
  projectPicker,
}: {
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: (value: string) => void;
  submitDisabled: boolean;
  placeholder: string;
  projectPicker?: ReactNode;
}) {
  const canSubmit = Boolean(value.trim()) && !submitDisabled;
  const submit = useCallback(() => {
    const text = value.trim();
    if (!text || submitDisabled) return;
    onValueChange("");
    onSubmit(text);
  }, [onSubmit, onValueChange, submitDisabled, value]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      !canSubmit
    ) {
      return;
    }
    event.preventDefault();
    submit();
  };

  return (
    <div
      data-testid="standalone-chat-composer"
      className="mx-auto w-full max-w-3xl px-6 pb-6 pt-3"
    >
      <div className="relative overflow-hidden rounded-2xl border border-[var(--color-border-hover)] bg-[var(--color-bg-input)] shadow-2xl shadow-black/20 transition-colors focus-within:border-[var(--color-border-active)]">
        {projectPicker && (
          <div className="flex items-center border-b border-[var(--color-border)] px-4 py-2.5">
            {projectPicker}
          </div>
        )}
        <textarea
          data-chat-composer
          rows={1}
          autoFocus
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="max-h-48 min-h-14 w-full resize-none border-0 bg-transparent px-4 py-4 pr-14 text-sm leading-6 text-[var(--color-text)] shadow-none outline-none placeholder:text-[var(--color-text-dim)] focus:border-0 focus:shadow-none focus:outline-none focus-visible:outline-none focus-visible:ring-0"
        />
        <button
          type="button"
          disabled={!canSubmit}
          onClick={submit}
          aria-label="Send message"
          className="absolute bottom-3 right-3 flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-text)] text-[var(--color-bg)] disabled:cursor-not-allowed disabled:opacity-30"
        >
          <Send className="h-3.5 w-3.5" />
        </button>
      </div>
      <p className="mt-2 text-center text-[10px] text-[var(--color-text-dim)]">
        Answers use governed, read-only access. Check freshness and caveats.
      </p>
    </div>
  );
}
