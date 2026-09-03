"use client";

import { ChevronRight } from "lucide-react";
import { useId } from "react";
import type { Connector } from "~/lib/api/mcp-connectors";
import {
  connectorSubtitle,
  deriveConnectorHealth,
  describeToolCount,
} from "~/lib/mcp-connectors-state";
import { Switch } from "~/components/ui/switch";
import { ConnectorGlyph } from "./connector-glyph";
import { ConnectorStatusPill } from "./connector-status-pill";
import { Button, KebabMenu, type MenuItem, FOCUS_RING } from "./ui";
import type { ConnectorActions } from "./use-connector-actions";

export type ConnectorRowProps = {
  connector: Connector;
  isAdmin: boolean;
  actions: ConnectorActions;
  onOpen: (connector: Connector, tab?: "tools" | "access" | "activity" | "settings") => void;
  onRemove: (connector: Connector) => void;
};

/**
 * One connector. Three fixed slots — glyph + name/subtitle, health pill,
 * tools + switch + kebab — so rows line up in a column at any width.
 *
 * Accessibility: the name is a real <button> that opens the drawer, and its
 * hit area is stretched over the row with a pseudo-element. The switch and
 * kebab are siblings above it (`relative z-10`), never nested inside a
 * button role. One switch, one truth: org rows carry the member's
 * "On for me"; personal rows carry the connector's own "On".
 */
export function ConnectorRow({ connector, isAdmin, actions, onOpen, onRemove }: ConnectorRowProps) {
  const health = deriveConnectorHealth(connector);
  const canManage = connector.scope === "personal" || isAdmin;
  const busy = actions.isBusy(connector.id);
  const personal = connector.scope === "personal";
  const onForMe = connector.my_state?.enabled ?? true;
  const switchId = useId();
  const toolsOn = Math.max(
    0,
    connector.enabled_tool_count - (connector.my_state?.disabled_tools.length ?? 0),
  );

  const menu: MenuItem[] = [
    { label: "Tools", onSelect: () => onOpen(connector, "tools") },
    { label: "Access", onSelect: () => onOpen(connector, "access") },
    { label: "Activity", onSelect: () => onOpen(connector, "activity") },
  ];
  if (canManage) {
    menu.push({
      label: connector.enabled
        ? connector.scope === "org"
          ? "Turn off for everyone"
          : "Turn off"
        : "Turn on",
      onSelect: () => void actions.setEnabled(connector, !connector.enabled),
    });
    menu.push({ label: "Remove…", danger: true, onSelect: () => onRemove(connector) });
  }

  const small = "min-h-[32px] px-3 text-[12px]";
  const primaryAction =
    health.action === "sign_in" ? (
      <Button variant="primary" pending={busy} data-testid="connector-row-sign-in" onClick={() => void actions.signIn(connector)} className={small}>
        Sign in
      </Button>
    ) : health.action === "add_key" ? (
      <Button variant="primary" onClick={() => onOpen(connector, "access")} className={small}>
        Add key
      </Button>
    ) : health.action === "retry" ? (
      <Button pending={busy} onClick={() => void actions.retry(connector)} className={small}>
        Retry
      </Button>
    ) : health.action === "review" && canManage ? (
      <Button onClick={() => onOpen(connector, "tools")} className={small}>
        Review
      </Button>
    ) : null;

  // Personal rows: the switch is the connector's own "On" (enabled). Org
  // rows: the member's "On for me". A personal connector that is off shows
  // the switch off so one flick turns it back on.
  const switchLabel = personal ? "On" : "On for me";
  const switchChecked = personal ? connector.enabled : onForMe;
  const switchDisabled = personal ? false : !connector.enabled;
  const onSwitch = (next: boolean) =>
    personal ? void actions.setEnabled(connector, next) : void actions.toggleForMe(connector, next);

  return (
    <div
      data-testid="connector-row"
      data-connector-id={connector.id}
      className="group relative flex min-h-[64px] items-center gap-3 px-3 py-2.5 transition-colors hover:bg-[var(--color-bg-hover)] focus-within:bg-[var(--color-bg-hover)] sm:gap-4 sm:px-4"
    >
      <ConnectorGlyph connector={connector} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            data-testid="connector-row-open"
            aria-label={`${connector.name}, ${health.label}. Open details`}
            onClick={() => onOpen(connector)}
            className={`truncate rounded-[4px] text-left text-[13.5px] font-medium text-[var(--color-text)] after:absolute after:inset-0 after:cursor-pointer after:content-[''] ${FOCUS_RING} focus-visible:ring-offset-0`}
          >
            {connector.name}
          </button>
          <span className="sm:hidden">
            <ConnectorStatusPill health={health} size="sm" testId="connector-status-pill-compact" />
          </span>
        </div>
        <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11.5px] text-[var(--color-text-dim)]">
          <span className="truncate font-mono">{connectorSubtitle(connector)}</span>
          {health.detail && (
            <>
              <span aria-hidden="true">·</span>
              <span className="truncate" data-testid="connector-row-detail">
                {health.detail}
              </span>
            </>
          )}
        </div>
      </div>
      <div className="hidden w-[124px] flex-none sm:block">
        <ConnectorStatusPill health={health} />
      </div>
      <span
        className="hidden w-[108px] flex-none text-right text-[11.5px] tabular-nums text-[var(--color-text-muted)] lg:block"
        data-testid="connector-row-tools"
      >
        {describeToolCount(connector.tool_count, toolsOn)}
      </span>
      {primaryAction ? (
        <div className="relative z-10 flex-none">{primaryAction}</div>
      ) : (
        <div className="relative z-10 flex flex-none items-center gap-2">
          <span id={switchId} className="hidden text-[11px] text-[var(--color-text-dim)] lg:block">
            {switchLabel}
          </span>
          <Switch
            size="sm"
            checked={switchChecked}
            busy={busy}
            disabled={switchDisabled}
            aria-labelledby={switchId}
            aria-label={`${switchLabel}: ${connector.name}`}
            data-testid={personal ? "connector-row-enabled" : "connector-row-on-for-me"}
            onCheckedChange={onSwitch}
          />
        </div>
      )}
      <KebabMenu items={menu} label={`More actions for ${connector.name}`} testId="connector-row-menu" />
      <ChevronRight
        className="hidden h-4 w-4 flex-none text-[var(--color-text-dim)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 sm:block"
        aria-hidden="true"
      />
    </div>
  );
}
