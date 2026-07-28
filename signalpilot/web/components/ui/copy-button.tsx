"use client";

import { useState } from "react";
import { Copy, CheckCircle2 } from "lucide-react";

/** `label` defaults to "copy key" — this started life on the API-keys page.
 *  Pass it when the payload is not a key (a command, a URL, a snippet). */
export function CopyButton({ text, label = "copy key" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors duration-150"
    >
      {copied ? (
        <>
          <CheckCircle2 className="w-3 h-3 text-[var(--color-success)]" />
          <span className="text-[var(--color-success)]">copied</span>
        </>
      ) : (
        <>
          <Copy className="w-3 h-3" />
          {label}
        </>
      )}
    </button>
  );
}
