"use client";

import { useState, useEffect, useRef } from "react";

export interface EditableFieldProps {
  value: string;
  onSave: (newValue: string) => void | Promise<void>;
  placeholder?: string;
  ariaLabel: string;
  variant: "input" | "textarea";
  displayClassName?: string;
}

export function EditableField({ value, onSave, placeholder, ariaLabel, variant, displayClassName }: EditableFieldProps) {
  const [editing, setEditing] = useState(false);
  const [localValue, setLocalValue] = useState(value);
  const inputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { if (!editing) setLocalValue(value); }, [value, editing]);
  useEffect(() => {
    if (!editing) return;
    if (variant === "input") { inputRef.current?.focus(); inputRef.current?.select(); }
    else { textareaRef.current?.focus(); textareaRef.current?.select(); }
  }, [editing, variant]);

  function enterEdit() { setLocalValue(value); setEditing(true); }
  async function commit() { setEditing(false); await onSave(localValue.trim()); }
  function cancel() { setEditing(false); setLocalValue(value); }

  if (editing && variant === "input") {
    return (
      <input ref={inputRef} value={localValue} onChange={(e) => setLocalValue(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void commit(); } else if (e.key === "Escape") cancel(); }}
        className={`bg-transparent border-b border-[var(--color-border-hover)] outline-none min-w-0 w-auto text-[var(--color-text)]${displayClassName ? ` ${displayClassName}` : ""}`}
        style={{ width: `${Math.max(localValue.length, 8)}ch` }} aria-label={ariaLabel} />
    );
  }
  if (editing) {
    return (
      <textarea ref={textareaRef} value={localValue} onChange={(e) => setLocalValue(e.target.value)}
        onBlur={() => void commit()} rows={2} placeholder={placeholder}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void commit(); } else if (e.key === "Escape") cancel(); }}
        className="text-sm text-[var(--color-text-muted)] tracking-wider bg-transparent border border-[var(--color-border)] outline-none resize-none w-full max-w-lg px-2 py-1 focus:border-[var(--color-border-hover)]"
        aria-label={ariaLabel} />
    );
  }
  function handleDisplayKey(e: React.KeyboardEvent) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); enterEdit(); } }

  if (!value) {
    return (
      <span className="italic text-[var(--color-text-dim)] cursor-pointer" onClick={enterEdit}
        tabIndex={0} role="button" onKeyDown={handleDisplayKey}
        title={`Click to edit ${ariaLabel.toLowerCase()}`} aria-label={ariaLabel}>
        {placeholder ?? ""}
      </span>
    );
  }
  return (
    <span className={`cursor-pointer hover:underline hover:underline-offset-2 hover:decoration-[var(--color-border-hover)] transition-all${displayClassName ? ` ${displayClassName}` : ""}`}
      onClick={enterEdit} tabIndex={0} role="button" onKeyDown={handleDisplayKey}
      title={`Click to edit ${ariaLabel.toLowerCase()}`} aria-label={ariaLabel}>
      {value}
    </span>
  );
}
