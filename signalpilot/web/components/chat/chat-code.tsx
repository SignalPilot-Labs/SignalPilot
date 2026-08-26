"use client";

import { Check, Copy } from "lucide-react";
import { memo, useMemo, useState, type ReactNode } from "react";
import { classHighlighter, highlightTree } from "@lezer/highlight";
import { parser as pythonParser } from "@lezer/python";
import { StandardSQL } from "@codemirror/lang-sql";

export type ChatCodeLanguage = "sql" | "python" | "bash" | "text";

function highlight(code: string, language: ChatCodeLanguage): ReactNode[] {
  const parser =
    language === "python"
      ? pythonParser
      : language === "sql"
        ? StandardSQL.language.parser
        : null;
  if (!parser) return [code];
  try {
    const tree = parser.parse(code);
    const children: ReactNode[] = [];
    let cursor = 0;
    highlightTree(tree, classHighlighter, (from, to, classes) => {
      if (from > cursor) children.push(code.slice(cursor, from));
      children.push(
        <span key={`${from}-${to}`} className={classes}>
          {code.slice(from, to)}
        </span>,
      );
      cursor = to;
    });
    if (cursor < code.length) children.push(code.slice(cursor));
    return children;
  } catch {
    return [code];
  }
}

export function CopyButton({
  text,
  label = "Copy",
}: {
  text: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => {
        void navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => undefined);
      }}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
    >
      {copied ? (
        <Check className="h-3 w-3 text-[var(--color-success)]" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
      {copied ? "Copied" : label}
    </button>
  );
}

/**
 * Static, dependency-light highlighted code block. Uses the lezer parsers the
 * notebook already ships instead of mounting a CodeMirror editor per block.
 */
export const ChatCode = memo(function ChatCode({
  code,
  language,
  maxHeightClass = "max-h-80",
}: {
  code: string;
  language: ChatCodeLanguage;
  maxHeightClass?: string;
}) {
  const trimmed = code.replace(/\s+$/, "");
  const children = useMemo(() => highlight(trimmed, language), [
    trimmed,
    language,
  ]);
  return (
    <pre
      className={`chat-code ${maxHeightClass} overflow-auto px-3.5 py-3 text-[12px] leading-[1.7] text-[var(--color-text-muted)]`}
    >
      <code>{children}</code>
    </pre>
  );
});
