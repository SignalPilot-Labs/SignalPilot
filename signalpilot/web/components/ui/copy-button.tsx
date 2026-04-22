"use client";

import { useState } from "react";
import { Copy, CheckCircle2 } from "lucide-react";

export function CopyButton({ text }: { text: string }) {
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
      className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider"
    >
      {copied ? (
        <>
          <CheckCircle2 className="w-3 h-3 text-[var(--color-success)]" />
          <span className="text-[var(--color-success)]">copied</span>
        </>
      ) : (
        <>
          <Copy className="w-3 h-3" />
          copy key
        </>
      )}
    </button>
  );
}
