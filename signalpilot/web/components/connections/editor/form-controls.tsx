"use client";

import { useState, type MutableRefObject, type Ref } from "react";
import { Eye, EyeOff } from "lucide-react";

export function FormInput({
  label, value, onChange, type = "text", placeholder, hint, required, className = "", error,
  id, inputRef,
}: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; placeholder?: string; hint?: string; required?: boolean; className?: string; error?: string;
  id?: string; inputRef?: Ref<HTMLInputElement>;
}) {
  const [visible, setVisible] = useState(false);
  const isSecret = type === "password";
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">
        {label}{required && <span className="text-[var(--color-error)] ml-0.5">*</span>}
      </label>
      <div className="relative">
        <input
          id={id}
          ref={inputRef}
          type={isSecret && !visible ? "password" : "text"}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={error && id ? `${id}-error` : undefined}
          className={`w-full px-3 py-2 ${isSecret ? "pr-9" : ""} bg-[var(--color-bg-input)] border rounded-[10px] text-xs focus:outline-none ${
            error ? "border-[var(--color-error)]/60 focus:border-[var(--color-error)]" : "border-[var(--color-border)] focus:border-[var(--color-text-dim)]"
          }`}
        />
        {isSecret && (
          <button
            type="button"
            tabIndex={-1}
            onClick={() => setVisible(!visible)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors cursor-pointer"
          >
            {visible ? <EyeOff className="w-3.5 h-3.5" strokeWidth={1.5} /> : <Eye className="w-3.5 h-3.5" strokeWidth={1.5} />}
          </button>
        )}
      </div>
      {error && id && <p id={`${id}-error`} role="alert" className="text-[11px] text-[var(--color-error)] mt-1">{error}</p>}
      {error && !id && <p className="text-[11px] text-[var(--color-error)] mt-1">{error}</p>}
      {hint && !error && <p className="text-[11px] text-[var(--color-text-dim)] mt-1 opacity-60">{hint}</p>}
    </div>
  );
}

export function FormTextArea({
  label, value, onChange, placeholder, hint, rows = 4, className = "", error,
  id, inputRef,
}: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; hint?: string; rows?: number; className?: string; error?: string;
  id?: string; inputRef?: Ref<HTMLTextAreaElement>;
}) {
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">{label}</label>
      <textarea
        id={id}
        ref={inputRef}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={error && id ? `${id}-error` : undefined}
        className={`w-full px-3 py-2 bg-[var(--color-bg-input)] border rounded-[10px] text-xs focus:outline-none font-mono resize-y ${
          error ? "border-[var(--color-error)]/60 focus:border-[var(--color-error)]" : "border-[var(--color-border)] focus:border-[var(--color-text-dim)]"
        }`}
      />
      {error && id && <p id={`${id}-error`} role="alert" className="text-[11px] text-[var(--color-error)] mt-1">{error}</p>}
      {error && !id && <p className="text-[11px] text-[var(--color-error)] mt-1">{error}</p>}
      {hint && !error && <p className="text-[11px] text-[var(--color-text-dim)] mt-1 opacity-60">{hint}</p>}
    </div>
  );
}

/** One-shot spread helper: returns id + inputRef + error for a given field key. */
export function fieldProps(
  key: string,
  formErrors: Record<string, string>,
  refMap: MutableRefObject<Record<string, HTMLElement | null>>,
) {
  return {
    id: key,
    inputRef: (el: HTMLElement | null) => { refMap.current[key] = el; },
    error: formErrors[key],
  };
}

/* ── Connection form state ── */




