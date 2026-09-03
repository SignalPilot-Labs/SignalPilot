"use client";

import { ArrowLeft, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Connector, ConnectorDetail } from "~/lib/api/mcp-connectors";
import { connectorSubtitle, deriveConnectorHealth } from "~/lib/mcp-connectors-state";
import { Skeleton } from "~/components/ui/skeleton";
import { useFocusTrap } from "~/components/ui/use-focus-trap";
import { useConnectors } from "./connectors-context";
import { ConnectorGlyph } from "./connector-glyph";
import { ConnectorStatusPill } from "./connector-status-pill";
import { DrawerAccessTab } from "./drawer-access-tab";
import { DrawerActivityTab } from "./drawer-activity-tab";
import { DrawerSettingsTab } from "./drawer-settings-tab";
import { DrawerToolsTab } from "./drawer-tools-tab";
import { Chip, FOCUS_RING } from "./ui";
import type { ConnectorActions } from "./use-connector-actions";

export type DrawerTab = "tools" | "access" | "activity" | "settings";
const TABS: { id: DrawerTab; label: string }[] = [
  { id: "tools", label: "Tools" },
  { id: "access", label: "Access" },
  { id: "activity", label: "Activity" },
  { id: "settings", label: "Settings" },
];

/**
 * Detail drawer: a right-side panel (≥ 560 px) on desktop, a full-screen
 * sheet under 768 px. Escape and the backdrop close it; focus lands on the
 * close control, is trapped inside while open, and returns to the row
 * afterwards.
 */
export function ConnectorDrawer({
  connector,
  initialTab = "tools",
  isAdmin,
  actions,
  onClose,
  onRemove,
}: {
  connector: Connector;
  initialTab?: DrawerTab;
  isAdmin: boolean;
  actions: ConnectorActions;
  onClose: () => void;
  onRemove: (connector: Connector) => void;
}) {
  const { api, upsert } = useConnectors();
  const [tab, setTab] = useState<DrawerTab>(initialTab);
  const [detail, setDetail] = useState<ConnectorDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  useFocusTrap(panelRef, true);

  useEffect(() => setTab(initialTab), [initialTab, connector.id]);

  const load = useCallback(async () => {
    try {
      const next = await api.get(connector.id);
      setDetail(next);
      setError(null);
    } catch (caught) {
      setError((caught as Error).message);
    }
  }, [api, connector.id]);

  useEffect(() => {
    setDetail(null);
    void load();
  }, [load]);

  // Keep the drawer in step with list-level changes (switch, sign-in).
  useEffect(() => {
    setDetail((current) => (current ? { ...current, ...connector, tools: current.tools } : current));
  }, [connector]);

  useEffect(() => {
    restoreFocus.current = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      restoreFocus.current?.focus?.();
    };
  }, [onClose]);

  const health = deriveConnectorHealth(connector);
  const applyDetail = (next: ConnectorDetail) => {
    setDetail(next);
    upsert(next);
  };

  return (
    <div
      className="fixed inset-0 z-[90] flex justify-end bg-black/55"
      onClick={onClose}
      data-testid="connector-drawer-backdrop"
    >
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="connector-drawer-title"
        data-testid="connector-drawer"
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full flex-col border-l border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/60 animate-slide-in-right md:w-[560px] md:min-w-[520px] lg:w-[600px]"
      >
        <header className="flex flex-none items-start gap-3 border-b border-[var(--color-border)] px-4 py-3.5 md:px-5">
          <button
            ref={closeRef}
            type="button"
            aria-label="Close"
            data-testid="connector-drawer-close"
            onClick={onClose}
            className={`-ml-1 mt-0.5 flex h-9 w-9 flex-none items-center justify-center rounded-[8px] text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)] ${FOCUS_RING}`}
          >
            <ArrowLeft className="h-4 w-4 md:hidden" aria-hidden="true" />
            <X className="hidden h-4 w-4 md:block" aria-hidden="true" />
          </button>
          <ConnectorGlyph connector={connector} size={40} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <h2 id="connector-drawer-title" className="truncate text-[15px] font-semibold text-[var(--color-text)]">
                {connector.name}
              </h2>
              <Chip>{connector.scope === "org" ? "Organization" : "Personal"}</Chip>
              {connector.transport === "stdio" && <Chip tone="write">Sandbox</Chip>}
            </div>
            <p className="mt-0.5 truncate font-mono text-[11.5px] text-[var(--color-text-dim)]">
              {connectorSubtitle(connector)}
            </p>
          </div>
          <div className="flex-none pt-0.5">
            <ConnectorStatusPill health={health} />
          </div>
        </header>
        <div
          role="tablist"
          aria-label="Connector sections"
          className="flex flex-none items-center gap-1 border-b border-[var(--color-border)] px-3 md:px-4"
        >
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              role="tab"
              id={`connector-tab-${entry.id}`}
              aria-selected={tab === entry.id}
              aria-controls={`connector-tabpanel-${entry.id}`}
              data-testid={`connector-tab-${entry.id}`}
              onClick={() => setTab(entry.id)}
              className={`relative min-h-[44px] px-3 text-[12.5px] transition-colors ${FOCUS_RING} focus-visible:ring-inset focus-visible:ring-offset-0 ${
                tab === entry.id
                  ? "font-medium text-[var(--color-text)]"
                  : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
              }`}
            >
              {entry.label}
              {tab === entry.id && (
                <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-[var(--color-success)]" aria-hidden="true" />
              )}
            </button>
          ))}
        </div>
        <div
          role="tabpanel"
          id={`connector-tabpanel-${tab}`}
          aria-labelledby={`connector-tab-${tab}`}
          data-testid="connector-drawer-body"
          className="min-h-0 flex-1 overflow-y-auto px-4 py-4 md:px-5"
        >
          {error ? (
            <p role="alert" className="text-[12.5px] text-[var(--color-error)]">
              We couldn&apos;t load this connector: {error}
            </p>
          ) : !detail ? (
            <div className="space-y-3" aria-busy="true">
              {Array.from({ length: 5 }, (_, i) => (
                <div key={i} className="flex items-center gap-3 rounded-[var(--radius-ctl)] border border-[var(--color-border)] px-3.5 py-3">
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3 w-40" />
                    <Skeleton className="h-2 w-64" />
                  </div>
                  <Skeleton className="h-4 w-8 rounded-full" />
                </div>
              ))}
            </div>
          ) : tab === "tools" ? (
            <DrawerToolsTab detail={detail} isAdmin={isAdmin} onDetail={applyDetail} />
          ) : tab === "access" ? (
            <DrawerAccessTab detail={detail} isAdmin={isAdmin} actions={actions} onDetail={applyDetail} />
          ) : tab === "activity" ? (
            <DrawerActivityTab connector={detail} />
          ) : (
            <DrawerSettingsTab
              detail={detail}
              isAdmin={isAdmin}
              actions={actions}
              onDetail={applyDetail}
              onRemove={() => onRemove(detail)}
            />
          )}
        </div>
      </aside>
    </div>
  );
}
