"use client";

import { AlertTriangle } from "lucide-react";
import { useId, useState } from "react";
import type { ToolInfo } from "~/lib/api/mcp-connectors";
import { TOOL_KIND_LABEL, toolKind } from "~/lib/mcp-connectors-state";
import { Switch } from "~/components/ui/switch";
import { Chip, FOCUS_RING } from "./ui";

/**
 * One tool: mono name, the provider's description as plain text (clamped to
 * two lines with "more"), an annotation chip, and a switch. Provider text is
 * quoted, never rendered as markup.
 *
 * `confirmBeforeOn`: turning the switch on first shows an inline confirm
 * strip (used for Destructive tools), so the one tool the product flagged
 * red never turns on with the same click as a read tool.
 */
export function ToolRow({
  tool,
  checked,
  onCheckedChange,
  disabled = false,
  disabledReason,
  busy = false,
  confirmBeforeOn = false,
}: {
  tool: ToolInfo;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  disabledReason?: string;
  busy?: boolean;
  confirmBeforeOn?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const labelId = useId();
  const kind = toolKind(tool.annotations);
  const long = tool.description.length > 120;

  const change = (next: boolean) => {
    if (next && confirmBeforeOn && !checked) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    onCheckedChange(next);
  };

  return (
    <li
      data-testid="tool-row"
      data-tool={tool.name}
      data-kind={kind}
      className={`min-h-[52px] px-3.5 py-2.5 ${confirming ? "bg-[var(--color-error)]/[0.04]" : ""}`}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span id={labelId} className="truncate font-mono text-[12.5px] text-[var(--color-text)]">
              {tool.title ?? tool.name}
            </span>
            {tool.is_new && <Chip tone="fresh">New</Chip>}
            <Chip tone={kind}>{TOOL_KIND_LABEL[kind]}</Chip>
          </div>
          {tool.description && (
            <p
              className={`mt-0.5 text-[11.5px] leading-[18px] text-[var(--color-text-dim)] ${
                expanded ? "" : "line-clamp-2"
              }`}
            >
              {tool.description}
              {long && expanded && " "}
              {long && expanded && (
                <button
                  type="button"
                  onClick={() => setExpanded(false)}
                  className={`text-[var(--color-text-muted)] underline underline-offset-2 ${FOCUS_RING}`}
                >
                  less
                </button>
              )}
            </p>
          )}
          {long && !expanded && (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className={`mt-0.5 text-[11px] text-[var(--color-text-muted)] underline underline-offset-2 ${FOCUS_RING}`}
            >
              more
            </button>
          )}
        </div>
        <div className="pt-0.5" title={disabled ? disabledReason : undefined}>
          <Switch
            size="sm"
            checked={checked || confirming}
            disabled={disabled}
            busy={busy}
            aria-labelledby={labelId}
            data-testid="tool-switch"
            onCheckedChange={change}
          />
        </div>
      </div>
      {confirming && (
        <div
          role="group"
          aria-label={`Confirm turning on ${tool.name}`}
          data-testid="tool-confirm"
          className="mt-2 flex flex-wrap items-center gap-2 rounded-[var(--radius-ctl)] border border-[var(--color-error)]/30 px-3 py-2 text-[12px]"
        >
          <AlertTriangle className="h-3.5 w-3.5 flex-none text-[var(--color-error)]" aria-hidden="true" />
          <span className="min-w-0 flex-1 text-[var(--color-text)]">
            Turn on <span className="font-mono">{tool.name}</span>? The provider says it can delete or destroy data.
          </span>
          <button
            type="button"
            data-testid="tool-confirm-yes"
            onClick={() => {
              setConfirming(false);
              onCheckedChange(true);
            }}
            className={`rounded-[8px] border border-[var(--color-error)]/40 bg-[var(--color-error)]/10 px-2.5 py-1 text-[12px] font-medium text-[var(--color-error)] hover:bg-[var(--color-error)]/18 ${FOCUS_RING}`}
          >
            Turn on
          </button>
          <button
            type="button"
            data-testid="tool-confirm-no"
            onClick={() => setConfirming(false)}
            className={`rounded-[8px] px-2.5 py-1 text-[12px] text-[var(--color-text-muted)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
          >
            Cancel
          </button>
        </div>
      )}
    </li>
  );
}
