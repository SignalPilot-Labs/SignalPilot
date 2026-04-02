"use client";

import { useState } from "react";

/**
 * Terminal-aesthetic code block with line numbers and copy button.
 */
export function CodeBlock({
  code,
  language = "sql",
  maxHeight = "16rem",
  showLineNumbers = true,
}: {
  code: string;
  language?: string;
  maxHeight?: string;
  showLineNumbers?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const lines = code.split("\n");

  function handleCopy() {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg)] overflow-hidden relative group">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-bg-card)]">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-30" />
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-20" />
          <span className="w-2 h-2 bg-[var(--color-text-dim)] opacity-10" />
        </div>
        <span className="text-[11px] text-[var(--color-text-dim)] tracking-[0.15em] uppercase">{language}</span>
        <button
          onClick={handleCopy}
          className="sm:opacity-0 sm:group-hover:opacity-100 transition-opacity text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] active:text-[var(--color-text)] tracking-wider flex items-center gap-1 px-1.5 py-1.5 sm:py-0.5 -mr-1.5 sm:-mr-0"
        >
          {copied ? (
            <>
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path d="M2 5L4 7L8 3" stroke="var(--color-success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              copied
            </>
          ) : (
            <>
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <rect x="3" y="3" width="6" height="6" stroke="currentColor" strokeWidth="0.75" />
                <path d="M1 7V1H7" stroke="currentColor" strokeWidth="0.75" />
              </svg>
              copy
            </>
          )}
        </button>
      </div>

      {/* Code */}
      <div className="overflow-auto" style={{ maxHeight }}>
        <div className="flex">
          {showLineNumbers && (
            <div className="flex-shrink-0 py-3 pl-3 pr-0 select-none border-r border-[var(--color-border)]">
              {lines.map((_, i) => (
                <div key={i} className="text-[12px] text-[var(--color-text-dim)] text-right pr-3 leading-[1.65rem] tabular-nums opacity-40">
                  {i + 1}
                </div>
              ))}
            </div>
          )}
          <pre className="flex-1 p-3 text-[13px] sm:text-[13px] text-[var(--color-text-muted)] leading-[1.65rem] tracking-wide overflow-x-auto [-webkit-overflow-scrolling:touch]">
            <code>{code}</code>
          </pre>
        </div>
      </div>
    </div>
  );
}
