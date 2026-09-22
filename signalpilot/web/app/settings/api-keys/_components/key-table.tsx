"use client";

import { Trash2 } from "lucide-react";
import type { ApiKeyResponse } from "~/lib/backend-client";

// ---------------------------------------------------------------------------
// Keys table row
// ---------------------------------------------------------------------------

export function KeyRow({
  apiKey,
  requestCount,
  onDelete,
}: {
  apiKey: ApiKeyResponse;
  requestCount: number;
  onDelete: (id: string) => void;
}) {
  const createdDate = new Date(apiKey.created_at).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  const lastUsed = apiKey.last_used_at
    ? new Date(apiKey.last_used_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "never";

  return (
    <div className="flex items-center gap-4 px-5 py-3 border-b border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors group">
      {/* Name */}
      <div className="flex-1 min-w-0">
        <span className="text-xs text-[var(--color-text-muted)]">
          {apiKey.name}
        </span>
      </div>

      {/* Prefix */}
      <code className="text-[12px] text-[var(--color-text-dim)] font-mono w-28 flex-shrink-0">
        {apiKey.prefix}...
      </code>

      {/* Scopes */}
      <div className="flex items-center gap-1.5 w-44 flex-shrink-0 flex-wrap">
        {apiKey.scopes.map((scope) => (
          <span
            key={scope}
            className="px-1.5 py-0.5 text-[11px] border border-[var(--color-border)] rounded-[6px] text-[var(--color-text-dim)]"
          >
            {scope}
          </span>
        ))}
      </div>

      {/* Created */}
      <span className="text-[12px] text-[var(--color-text-dim)] w-28 flex-shrink-0 font-mono tabular-nums">
        {createdDate}
      </span>

      {/* Last used */}
      <span className="text-[12px] text-[var(--color-text-dim)] w-24 flex-shrink-0 font-mono tabular-nums">
        {lastUsed}
      </span>

      {/* Requests */}
      <span className="text-[12px] text-[var(--color-text-dim)] w-20 flex-shrink-0 font-mono tabular-nums">
        {requestCount.toLocaleString()}
      </span>

      {/* Delete */}
      <button
        onClick={() => onDelete(apiKey.id)}
        aria-label={`delete api key ${apiKey.name}`}
        className="opacity-0 group-hover:opacity-100 flex items-center gap-1 px-2 py-1 text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/20 rounded-[6px] hover:bg-[var(--color-error)]/5 hover:border-[var(--color-error)]/40 transition-colors duration-150"
      >
        <Trash2 className="w-3 h-3" />
        delete
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table header
// ---------------------------------------------------------------------------

export function TableHeader() {
  return (
    <div className="flex items-center gap-4 px-5 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
      <span className="flex-1 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
        name
      </span>
      <span className="w-28 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
        prefix
      </span>
      <span className="w-44 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
        scopes
      </span>
      <span className="w-28 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
        created
      </span>
      <span className="w-24 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
        last used
      </span>
      <span className="w-20 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
        requests
      </span>
      <span className="w-16 flex-shrink-0" />
    </div>
  );
}
