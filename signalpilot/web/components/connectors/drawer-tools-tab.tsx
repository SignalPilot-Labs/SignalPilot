"use client";

import { Search, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import type { ConnectorDetail, ToolInfo } from "~/lib/api/mcp-connectors";
import {
  bulkToolSettings,
  countToolKinds,
  filterTools,
  filterToolsByKind,
  groupTools,
  TOOL_KIND_LABEL,
  toolKind,
  type ToolKind,
} from "~/lib/mcp-connectors-state";
import { useToast } from "~/components/ui/toast";
import { useConnectors } from "./connectors-context";
import { ToolRow } from "./tool-row";
import { Button, Eyebrow, Notice, TextInput, FOCUS_RING } from "./ui";

type Settings = Record<string, { enabled: boolean; policy: "auto" | "off" }>;
type KindFilter = ToolKind | "all";
const KIND_FILTERS: KindFilter[] = ["all", "read", "write", "destructive"];
const UNDO_MS = 5000;

/** Snapshot of the current policy for the tools a write touches (the Undo body). */
function snapshot(tools: ToolInfo[], names: string[]): Settings {
  const next: Settings = {};
  for (const tool of tools) {
    if (names.includes(tool.name)) {
      next[tool.name] = tool.enabled ? { enabled: true, policy: "auto" } : { enabled: false, policy: "off" };
    }
  }
  return next;
}

/** "3 added · 1 removed" when the gateway counted; else the new-tool count. */
export function describeToolsChanged(detail: Pick<ConnectorDetail, "tools_added" | "tools_removed">, newCount: number): string {
  const added = detail.tools_added ?? null;
  const removed = detail.tools_removed ?? null;
  if (added === null && removed === null) return `${newCount} new ${newCount === 1 ? "tool" : "tools"} since last check`;
  const parts: string[] = [];
  if (added) parts.push(`${added} added`);
  if (removed) parts.push(`${removed} removed`);
  return parts.length ? `${parts.join(" · ")} since last check` : "Tools changed since last check";
}

/**
 * Tools tab: search, kind filter chips, the tools-changed banner, two bulk
 * actions, and the On / Off groups. Every change gets a 5-second Undo toast;
 * turning on a Destructive tool asks for an inline confirm first. Admins
 * (or the owner) set the connector's policy; a member on an org connector
 * can only turn tools off for themselves.
 */
export function DrawerToolsTab({
  detail,
  isAdmin,
  onDetail,
}: {
  detail: ConnectorDetail;
  isAdmin: boolean;
  onDetail: (next: ConnectorDetail) => void;
}) {
  const { api } = useConnectors();
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const memberOnly = detail.scope === "org" && !isAdmin;
  const disabledForMe = detail.my_state?.disabled_tools ?? [];
  const counts = useMemo(() => countToolKinds(detail.tools), [detail.tools]);
  const groups = useMemo(
    () => groupTools(filterToolsByKind(filterTools(detail.tools, query), kind), disabledForMe),
    [detail.tools, disabledForMe, query, kind],
  );
  const newCount = detail.tools.filter((t) => t.is_new).length;

  const write = async (body: Settings, key: string, message: string, tone: "success" | "warning", undo: Settings | null) => {
    setBusy(key);
    try {
      onDetail(await api.updateTools(detail.id, { tools: body }));
      toast(
        `${message} · applies to new chats`,
        tone,
        undo ? UNDO_MS : 3000,
        undo
          ? {
              label: "Undo",
              onClick: () => void write(undo, `${key}-undo`, "Undone", "success", null),
            }
          : undefined,
      );
    } catch (error) {
      toast(`Couldn't update tools: ${(error as Error).message}`, "error");
    } finally {
      setBusy(null);
    }
  };

  const toggle = (tool: ToolInfo, enabled: boolean) => {
    const destructive = toolKind(tool.annotations) === "destructive";
    return write(
      { [tool.name]: enabled ? { enabled: true, policy: "auto" } : { enabled: false, policy: "off" } },
      tool.name,
      `${tool.name} turned ${enabled ? "on" : "off"}`,
      enabled && destructive ? "warning" : "success",
      snapshot(detail.tools, [tool.name]),
    );
  };

  const bulk = (action: "on_read_only" | "off_all") =>
    write(
      bulkToolSettings(detail.tools, action),
      action === "on_read_only" ? "bulk-read" : "bulk-off",
      action === "on_read_only" ? "Read-only tools turned on" : "All tools turned off",
      "success",
      snapshot(
        detail.tools,
        detail.tools.map((t) => t.name),
      ),
    );

  const acknowledgeNew = async () => {
    setBusy("refresh");
    try {
      onDetail(await api.refreshTools(detail.id));
      toast("New tools stay off until you turn them on", "success");
    } catch (error) {
      toast(`Couldn't update: ${(error as Error).message}`, "error");
    } finally {
      setBusy(null);
    }
  };

  const switchState = (tool: ToolInfo) => {
    const mine = disabledForMe.includes(tool.name);
    if (memberOnly) {
      return { checked: tool.enabled && !mine, disabled: !tool.enabled, reason: "Turned off by your admin" };
    }
    return { checked: tool.enabled, disabled: false, reason: undefined };
  };

  const group = (title: string, tools: ToolInfo[], testId: string) => (
    <section aria-label={`${title} tools`} data-testid={testId}>
      <div className="mb-2 flex items-center gap-2">
        <Eyebrow>{title}</Eyebrow>
        <span className="text-[11px] tabular-nums text-[var(--color-text-dim)]">{tools.length}</span>
        {tools.length > 0 && (
          <span className="text-[11px] text-[var(--color-text-dim)]">
            · {title === "On" ? "read-only first" : "writes first"}
          </span>
        )}
      </div>
      {tools.length === 0 ? (
        <p className="rounded-[var(--radius-ctl)] border border-dashed border-[var(--color-border)] px-3 py-3 text-[12px] text-[var(--color-text-dim)]">
          {query
            ? `No tools match "${query}".`
            : kind !== "all"
              ? `No ${TOOL_KIND_LABEL[kind].toLowerCase()} tools here.`
              : title === "On"
                ? "Nothing is on. The agent won't see this connector's tools."
                : "Everything is on."}
        </p>
      ) : (
        <ul className="divide-y divide-[var(--color-border)] rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          {tools.map((tool) => {
            const s = switchState(tool);
            return (
              <ToolRow
                key={tool.name}
                tool={tool}
                checked={s.checked}
                disabled={s.disabled}
                disabledReason={s.reason}
                busy={busy === tool.name}
                confirmBeforeOn={!memberOnly && toolKind(tool.annotations) === "destructive"}
                onCheckedChange={(enabled) => void toggle(tool, enabled)}
              />
            );
          })}
        </ul>
      )}
    </section>
  );

  if (detail.tools.length === 0) {
    return (
      <Notice tone="info" testId="drawer-tools-empty">
        This connector doesn&apos;t expose any tools yet.
        {detail.status === "unreachable" && " They'll appear once it can be reached."}
      </Notice>
    );
  }

  return (
    <div className="space-y-5">
      {(newCount > 0 || detail.status === "tools_changed") && (
        <Notice tone="warning" testId="drawer-tools-new-banner" icon={<Sparkles className="h-3.5 w-3.5" aria-hidden="true" />}>
          <p className="font-medium">{describeToolsChanged(detail, newCount)}</p>
          <p className="mt-0.5 text-[var(--color-text-muted)]">
            {memberOnly
              ? "New tools stay off until your admin reviews them."
              : "New tools are off. Review them below and turn on what you want the agent to have."}
          </p>
          {!memberOnly && (
            <div className="mt-2">
              <Button pending={busy === "refresh"} onClick={() => void acknowledgeNew()} className="min-h-[30px] px-2.5 text-[11.5px]" data-testid="drawer-tools-acknowledge">
                Keep them off
              </Button>
            </div>
          )}
        </Notice>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-dim)]" aria-hidden="true" />
          <TextInput
            aria-label="Search tools"
            placeholder="Search tools"
            value={query}
            data-testid="drawer-tools-search"
            onChange={(e) => setQuery(e.target.value)}
            className="min-h-[36px] pl-9 text-[12.5px]"
          />
        </div>
        {!memberOnly && (
          <>
            <Button pending={busy === "bulk-read"} data-testid="drawer-tools-on-read-only" onClick={() => void bulk("on_read_only")} className="min-h-[36px] text-[12px]">
              Turn on all read-only
            </Button>
            <Button pending={busy === "bulk-off"} data-testid="drawer-tools-off-all" onClick={() => void bulk("off_all")} className="min-h-[36px] text-[12px]">
              Turn off all
            </Button>
          </>
        )}
      </div>

      <div role="radiogroup" aria-label="Filter by kind" className="flex flex-wrap items-center gap-1.5" data-testid="drawer-tools-kinds">
        {KIND_FILTERS.map((value) => {
          const active = kind === value;
          const label = value === "all" ? "All" : TOOL_KIND_LABEL[value];
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={active}
              data-testid={`drawer-tools-kind-${value}`}
              onClick={() => setKind(value)}
              className={`inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] transition-colors ${FOCUS_RING} ${
                active
                  ? "border-[var(--color-text)]/30 bg-[var(--color-text)]/[0.08] text-[var(--color-text)]"
                  : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
              }`}
            >
              {label}
              <span className="tabular-nums text-[var(--color-text-dim)]">{counts[value]}</span>
            </button>
          );
        })}
      </div>

      <p className="text-[11.5px] leading-5 text-[var(--color-text-dim)]">
        Descriptions and read-only labels come from the provider and aren&apos;t checked by SignalPilot.
        {detail.transport === "stdio"
          ? " Switches on a sandbox connector are enforced by the agent's tool permissions, not by SignalPilot."
          : " Switches are enforced on every call."}
        {memberOnly && " You can turn tools off for yourself; your admin decides what's on."}
      </p>

      {group("On", groups.on, "drawer-tools-on")}
      {group("Off", groups.off, "drawer-tools-off")}
    </div>
  );
}
