"use client";

import React, { useId, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { CopyButton } from "@/components/ui/copy-button";
import { PRIMARY_BTN_CLASS } from "@/components/auth/auth-primitives";

export interface RevealOnceProps {
  title: string;
  description: string;
  lines: string[];
  onDismiss: () => void;
}

export function RevealOnce({ title, description, lines, onDismiss }: RevealOnceProps): React.JSX.Element {
  const allText = lines.join("\n");
  const titleId = useId();
  const checkboxId = useId();
  const [confirmed, setConfirmed] = useState(false);

  return (
    <div
      role="region"
      aria-labelledby={titleId}
      className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 space-y-4 animate-fade-in"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-warning)] flex-shrink-0 mt-0.5" strokeWidth={1.5} />
        <div>
          <p id={titleId} className="text-[12px] text-[var(--color-text-muted)] uppercase tracking-[0.15em] mb-1">{title}</p>
          <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">{description}</p>
        </div>
      </div>

      {/* aria-live so screen readers announce when codes appear */}
      <div
        aria-live="polite"
        aria-atomic="true"
        className="grid grid-cols-2 md:grid-cols-5 gap-2 p-3 bg-[var(--color-bg)] border border-[var(--color-border)]"
      >
        {lines.map((line) => (
          <code
            key={line}
            className="text-[12px] text-[var(--color-text)] font-mono tracking-widest whitespace-nowrap"
          >
            {line}
          </code>
        ))}
      </div>

      <div className="flex items-center justify-between gap-3">
        <CopyButton text={allText} />
      </div>

      {/* Friction checkpoint before dismissal */}
      <label
        htmlFor={checkboxId}
        className="flex items-center gap-2 cursor-pointer select-none"
      >
        <input
          id={checkboxId}
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
          className="w-3.5 h-3.5 accent-[var(--color-text)] cursor-pointer focus-visible:outline focus-visible:outline-1 focus-visible:outline-[var(--color-text)]"
        />
        <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">
          i have copied these codes somewhere safe
        </span>
      </label>

      <button
        onClick={onDismiss}
        disabled={!confirmed}
        className={PRIMARY_BTN_CLASS}
        aria-disabled={!confirmed}
      >
        done
      </button>
    </div>
  );
}
