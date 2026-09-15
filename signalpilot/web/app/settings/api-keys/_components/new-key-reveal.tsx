"use client";

import { AlertTriangle } from "lucide-react";
import type { ApiKeyCreatedResponse } from "~/lib/backend-client";
import { CopyButton } from "~/components/ui/copy-button";

// ---------------------------------------------------------------------------
// New key revealed panel
// ---------------------------------------------------------------------------

export function NewKeyReveal({
  created,
  onDismiss,
}: {
  created: ApiKeyCreatedResponse;
  onDismiss: () => void;
}) {
  const mcpUrl = `${process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300"}/mcp`;
  const mcpConfig = JSON.stringify({
    mcpServers: {
      signalpilot: {
        type: "http",
        url: mcpUrl,
        headers: { "X-API-Key": created.raw_key },
      },
    },
  }, null, 2);

  const claudeCodeCmd = `claude mcp add --transport http signalpilot ${mcpUrl} --header "Authorization: Bearer ${created.raw_key}"`;

  return (
    <div className="border border-[var(--color-success)]/30 bg-[var(--color-success)]/5 rounded-[14px] p-5 animate-fade-in">
      {/* Warning banner */}
      <div className="flex items-start gap-2 mb-4">
        <AlertTriangle
          className="w-3.5 h-3.5 text-[var(--color-warning)] mt-0.5 flex-shrink-0"
          strokeWidth={1.5}
        />
        <p className="text-[12px] text-[var(--color-warning)] leading-relaxed">
          copy this key now. it will not be shown again.
        </p>
      </div>

      {/* Key display */}
      <div className="flex items-center gap-3 mb-4">
        <code className="flex-1 px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[13px] text-[var(--color-success)] break-all font-mono">
          {created.raw_key}
        </code>
        <CopyButton text={created.raw_key} />
      </div>

      {/* Key metadata */}
      <div className="flex items-center gap-6 text-[11px] text-[var(--color-text-dim)] mb-4">
        <span>
          name: <span className="text-[var(--color-text-muted)]">{created.name}</span>
        </span>
        <span>
          prefix: <code className="text-[var(--color-text-muted)]">{created.prefix}</code>
        </span>
        <span>
          scopes:{" "}
          <span className="text-[var(--color-text-muted)]">{created.scopes.join(", ")}</span>
        </span>
      </div>

      {/* Claude Code one-liner */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] text-[var(--color-text-dim)]">claude code — one-liner</span>
          <CopyButton text={claudeCodeCmd} />
        </div>
        <pre className="px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[11px] text-[var(--color-success)] font-mono overflow-x-auto whitespace-pre">
{claudeCodeCmd}
        </pre>
      </div>

      {/* MCP connection config */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] text-[var(--color-text-dim)]">mcp json config</span>
          <CopyButton text={mcpConfig} />
        </div>
        <pre className="px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[11px] text-[var(--color-text-muted)] font-mono overflow-x-auto whitespace-pre">
{mcpConfig}
        </pre>
        <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">
          paste into .mcp.json (Claude Code) or .cursor/mcp.json (Cursor)
        </p>
      </div>

      <button
        onClick={onDismiss}
        className="text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150"
      >
        i&apos;ve copied it, dismiss
      </button>
    </div>
  );
}
