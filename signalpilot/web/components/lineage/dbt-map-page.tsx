"use client";

/**
 * The dbt map — SignalPilot's lineage home. Composes the split pieces:
 * data hook (use-dbt-map), header (map-header), schema window / focus panel,
 * canvas (map-canvas), inspector, and the deep-link machinery:
 *
 *   /lineage                       full map
 *   /lineage/<model>               focus mode (name or dbt unique_id)
 *   /lineage/<model>/raw           focus mode, Raw Tables panel
 *
 * URL state follows the knowledge-page pattern: seeded from the route, then
 * kept in sync with history.replaceState. A route change that the page did
 * not produce itself (a chat link clicked while on /lineage, the modal
 * pointed at another model) updates focus in place: the page never
 * remounts, so the cached project graph stays on screen. Focus is the
 * shareable unit; selection stays out of the URL.
 *
 * `embedded` mode (the chat lineage modal) keeps the same body, canvas and
 * panels but drops the page chrome: no header, no URL sync, no remembered
 * project, no global "/" and Escape shortcuts, and it fills its host instead
 * of the viewport. See lineage-embed.tsx for the public wrapper.
 */

import { Hammer, Loader2 } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";

import { Skeleton } from "~/components/ui/skeleton";
import { LAYER_ORDER, type MapLayer } from "./palette";
import { MapCanvas } from "./map-canvas";
import { MapHeader } from "./map-header";
import { SchemaWindow } from "./schema-window";
import { FocusPanel } from "./focus-panel";
import { Inspector, type InspectorTab } from "./inspector";
import { leftPanelCollapses, widthFittingPanel } from "./inspector-resize";
import { useInspectorWidth } from "./use-inspector-width";
import { PanelRail } from "./panel-rail";
import { LayerLegend } from "./layer-legend";
import { NotFoundCard, UnmappedCard } from "./not-found-card";
import { useDbtMap, useModelColumns, useModelSql, type MapStatus } from "./use-dbt-map";
import {
  canonicalRef,
  lineagePath,
  pathBetween,
  resolveModelRef,
  type LineageRoute,
} from "./lineage-nav";

export type { LineageRoute };

function LoadingSkeleton() {
  return (
    <div className="flex h-full">
      <div className="hidden w-60 shrink-0 flex-col gap-2 border-r border-[var(--color-border)] bg-[var(--color-bg-card)]/60 p-3 md:flex">
        <Skeleton className="h-2.5 w-16" />
        {Array.from({ length: 9 }, (_, i) => (
          <Skeleton key={i} className={`h-2.5 ${i % 3 === 0 ? "w-28" : i % 3 === 1 ? "w-36" : "w-24"}`} />
        ))}
      </div>
      <div className="flex flex-1 items-center justify-center">
        <div className="grid grid-cols-3 gap-x-16 gap-y-8">
          {Array.from({ length: 9 }, (_, i) => (
            <Skeleton key={i} className="h-[52px] w-[180px] rounded-[10px]" />
          ))}
        </div>
      </div>
    </div>
  );
}

export function DbtMapPage({
  route,
  embedded = false,
  onStatusChange,
}: {
  route?: LineageRoute;
  embedded?: boolean;
  onStatusChange?: (status: MapStatus) => void;
}) {
  const map = useDbtMap(route?.projectId ?? null, route?.ref ?? null, {
    remember: !embedded,
    onStatusChange,
  });
  const { parsed, mapInfo, mapStatus, compiling, compileNow } = map;

  const [visibleLayers, setVisibleLayers] = useState<Set<MapLayer>>(new Set(LAYER_ORDER));
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  /** The focused model as a URL ref (name or unique_id); null = full map. */
  const [focusTarget, setFocusTarget] = useState<string | null>(route?.ref ?? null);
  const [rawView, setRawView] = useState<boolean>(route?.raw ?? false);
  const [highlightSource, setHighlightSource] = useState<string | null>(null);
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("details");
  const searchRef = useRef<HTMLInputElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);

  // Resolve the focus target against the loaded graph.
  const resolution = useMemo(
    () => (parsed && focusTarget ? resolveModelRef(parsed, focusTarget) : null),
    [parsed, focusTarget],
  );
  const focusId = resolution?.kind === "found" ? resolution.id : null;
  const focusModel = focusId && parsed ? parsed.models.get(focusId) ?? null : null;

  // Inspector width: owned here so the left panel can yield to the rail.
  // Full left panel widths: focus panel w-72, schema window w-60.
  const leftPanelWidth = focusId ? 288 : 240;
  const inspectorSize = useInspectorWidth(rowRef, embedded ? "modal" : "page", leftPanelWidth);

  // Canonical share path for the current view (drives the URL + copy-link).
  const focusPath = useMemo(() => {
    if (!focusTarget) return null;
    const ref = parsed && focusId ? canonicalRef(parsed, focusId) : focusTarget;
    return lineagePath(ref, rawView);
  }, [parsed, focusTarget, focusId, rawView]);

  // Route changes from outside (props) re-seed focus without a remount. The
  // page's own replaceState echoes back as the current path and is ignored.
  const routeRef = route?.ref ?? null;
  const routeRaw = route?.raw ?? false;
  useEffect(() => {
    const incoming = routeRef ? lineagePath(routeRef, routeRaw) : null;
    if (incoming === focusPath) return;
    setFocusTarget(routeRef);
    setRawView(routeRaw);
    setHighlightSource(null);
    setSelectedId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeRef, routeRaw]);

  // Time-to-focused-node instrumentation: marked once per focus target.
  const markedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!focusModel || markedRef.current === focusModel.id) return;
    markedRef.current = focusModel.id;
    if (typeof performance !== "undefined" && performance.mark) {
      performance.mark("sp:lineage:focus-ready", { detail: focusModel.id });
    }
  }, [focusModel]);

  // URL sync — knowledge-page pattern (replaceState; focus is shareable,
  // selection is not). The not-found case keeps the bad URL visible.
  useEffect(() => {
    if (embedded || typeof window === "undefined") return;
    const path = focusPath ?? "/lineage";
    const url = `${path}${window.location.search}`;
    if (window.location.pathname + window.location.search !== url) {
      window.history.replaceState(null, "", url);
    }
  }, [focusPath, embedded]);

  // Switching projects (after boot) drops focus/selection: model ids don't
  // carry across projects. A switch the route asked for keeps its own ref.
  const prevProject = useRef<string | null>(null);
  useEffect(() => {
    if (prevProject.current && prevProject.current !== map.projectId) {
      const fromRoute = route?.projectId === map.projectId;
      setSelectedId(null);
      setFocusTarget(fromRoute ? route?.ref ?? null : null);
      setRawView(fromRoute ? route?.raw ?? false : false);
      setHighlightSource(null);
    }
    prevProject.current = map.projectId;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map.projectId]);

  // Leaving focus mode clears raw view + path highlight.
  useEffect(() => {
    if (!focusId) {
      setHighlightSource(null);
      if (!focusTarget) setRawView(false);
    }
  }, [focusId, focusTarget]);

  const exitFocus = () => {
    setFocusTarget(null);
    setRawView(false);
    setHighlightSource(null);
  };

  const focusOn = (id: string | null) => {
    if (!parsed) return;
    if (id === null || id === focusId) {
      exitFocus();
      return;
    }
    setFocusTarget(canonicalRef(parsed, id));
    setRawView(false);
    setHighlightSource(null);
  };

  // Keyboard: "/" focuses search (also inside focus mode — it searches the
  // cone). Escape inside the search field clears it (then blurs) — the
  // universal field convention — and only when the canvas owns focus does the
  // ladder apply: raw view -> focus -> selection. Embedded hosts own the
  // keyboard (the modal closes on Escape), so the shortcuts stay off there.
  useEffect(() => {
    if (embedded) return;
    const onKey = (e: KeyboardEvent) => {
      const active = document.activeElement as HTMLElement | null;
      const inField =
        !!active &&
        (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable);
      if (e.key === "/" && !inField) {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === "Escape") {
        if (active && active === searchRef.current) {
          e.preventDefault();
          if (query) setQuery("");
          else searchRef.current?.blur();
          return;
        }
        if (inField) return;
        if (rawView) setRawView(false);
        else if (focusTarget) exitFocus();
        else setSelectedId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawView, focusTarget, query, embedded]);

  const highlightIds = useMemo(
    () =>
      parsed && focusId && highlightSource
        ? pathBetween(parsed, highlightSource, focusId)
        : null,
    [parsed, focusId, highlightSource],
  );

  const selected = selectedId && parsed ? parsed.models.get(selectedId) ?? null : null;
  const lazyColumns = useModelColumns(
    map.projectId,
    selected && !selected.columnsLoaded ? selected.id : null,
  );
  const selectedColumns = selected?.columnsLoaded ? selected.columns : lazyColumns.columns;
  // SQL loads only once the tab is open; sources never have any.
  const sqlState = useModelSql(
    map.projectId,
    selected && selected.layer !== "source" ? selected.id : null,
    inspectorTab === "sql",
  );
  const selectedSql = selected?.layer === "source" ? ({ state: "unavailable" } as const) : sqlState;
  // A cone-only graph cannot judge an unknown ref; wait for the skeleton.
  const unresolved = Boolean(
    parsed && !map.partial && focusTarget && resolution && resolution.kind !== "found",
  );

  // When the open inspector leaves less than the canvas reserve, the panel
  // collapses to a rail and the rail button hands the width back.
  const leftCollapsed =
    Boolean(selected && parsed) &&
    leftPanelCollapses(inspectorSize.containerWidth, inspectorSize.width, leftPanelWidth);
  const restoreLeftPanel = () =>
    inspectorSize.commit(widthFittingPanel(inspectorSize.containerWidth, leftPanelWidth));

  return (
    <div
      className={`flex flex-col overflow-hidden ${embedded ? "h-full" : "h-screen"}`}
      data-testid={embedded ? "lineage-embed" : "lineage-page"}
      data-graph={map.partial ? "cone" : parsed ? "full" : "none"}
      data-focus-ready={focusModel ? "1" : "0"}
    >
      {!embedded && (
        <MapHeader
          projects={map.projects}
          projectId={map.projectId}
          onProjectChange={map.setProjectId}
          query={query}
          onQueryChange={setQuery}
          searchRef={searchRef}
          focusModel={focusModel}
          rawView={rawView}
          focusUrl={focusPath}
          onExitFocus={exitFocus}
          mapInfo={mapInfo}
          mapStatus={mapStatus}
          watched={map.watched}
          compiling={compiling}
          onCompile={() => void compileNow()}
        />
      )}

      <div ref={rowRef} className="flex min-h-0 flex-1" data-testid="lineage-row">
        {parsed && leftCollapsed ? (
          <PanelRail label={focusId ? "lineage" : "schemas"} onExpand={restoreLeftPanel} />
        ) : parsed &&
          (focusId ? (
            <FocusPanel
              parsed={parsed}
              focusId={focusId}
              tab={rawView ? "raw" : "lineage"}
              selectedId={selectedId}
              onTabChange={(tab) => setRawView(tab === "raw")}
              onSelect={(id) => setSelectedId(id)}
              onHighlightSource={setHighlightSource}
            />
          ) : (
            <SchemaWindow
              parsed={parsed}
              query={query}
              selectedId={selectedId}
              onSelect={(id) => setSelectedId(id)}
            />
          ))}

        <div className="relative min-w-0 flex-1 bg-[var(--color-bg)]" data-testid="lineage-canvas" data-tour-id="lineage-canvas">
          {parsed ? (
            <>
              <ReactFlowProvider>
                <MapCanvas
                  parsed={parsed}
                  visibleLayers={visibleLayers}
                  query={query}
                  selectedId={selectedId}
                  focusId={focusId}
                  highlightIds={highlightIds}
                  onSelect={setSelectedId}
                  onFocus={focusOn}
                />
              </ReactFlowProvider>
              {unresolved && resolution && focusTarget && (
                <NotFoundCard
                  parsed={parsed}
                  targetRef={focusTarget}
                  resolution={resolution}
                  onPick={(ref) => setFocusTarget(ref)}
                  onShowFullMap={exitFocus}
                />
              )}
              {/* Full-map chrome only: in focus mode the stage captions +
                  panel carry the layer story, and the full-map counts would
                  contradict the cone-scoped ones next to them. */}
              {!focusId && (
                <LayerLegend
                  parsed={parsed}
                  visibleLayers={visibleLayers}
                  onToggle={(layer) =>
                    setVisibleLayers((prev) => {
                      const next = new Set(prev);
                      if (next.has(layer)) next.delete(layer);
                      else next.add(layer);
                      return next;
                    })
                  }
                />
              )}
            </>
          ) : mapStatus === "loading" ? (
            <LoadingSkeleton />
          ) : focusTarget && (mapStatus === "none" || mapStatus === "failed") ? (
            <UnmappedCard
              targetRef={focusTarget}
              status={mapStatus}
              compiling={compiling}
              onCompile={() => void compileNow()}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              {mapStatus === "running" || mapStatus === "queued" ? (
                <>
                  <Loader2 className="h-5 w-5 animate-spin text-[var(--color-warning)]" />
                  <p className="text-xs text-[var(--color-text-muted)]">compiling the dbt map on a sandbox…</p>
                  <p className="text-[10px] text-[var(--color-text-dim)]">this page updates itself when it lands</p>
                </>
              ) : mapStatus === "failed" ? (
                <>
                  <p className="text-xs text-[var(--color-error)]">last compile failed</p>
                  <p className="max-w-md font-mono text-[10px] text-[var(--color-text-dim)]">{mapInfo?.error}</p>
                  <button type="button" onClick={() => void compileNow()} className="rounded-[8px] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text)] hover:border-[var(--color-border-hover)]">
                    retry compile
                  </button>
                </>
              ) : mapStatus === "no-projects" ? (
                <p className="text-xs text-[var(--color-text-dim)]">no projects yet — link a GitHub repo to get started</p>
              ) : (
                <>
                  <p className="text-xs text-[var(--color-text-muted)]">no dbt map compiled for this project yet</p>
                  <button type="button" onClick={() => void compileNow()} disabled={compiling} className="flex items-center gap-1.5 rounded-[8px] border border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text)] hover:border-[var(--color-border-hover)] disabled:opacity-50">
                    <Hammer className="h-3 w-3" /> compile dbt map
                  </button>
                  <p className="text-[10px] text-[var(--color-text-dim)]">runs dbt parse on a sandbox — no warehouse access needed</p>
                </>
              )}
            </div>
          )}
        </div>

        {selected && parsed && (
          <Inspector
            parsed={parsed}
            model={selected}
            columns={selectedColumns}
            sql={selectedSql}
            tab={inspectorTab}
            onTabChange={setInspectorTab}
            isFocused={selected.id === focusId}
            onClose={() => setSelectedId(null)}
            onNavigate={(id) => setSelectedId(id)}
            onFocus={focusOn}
            size={inspectorSize}
          />
        )}
      </div>
    </div>
  );
}
