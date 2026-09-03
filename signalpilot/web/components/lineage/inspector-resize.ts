/**
 * Width rules for the resizable lineage inspector. Pure: the hook
 * (use-inspector-width.ts) and the handle (inspector-resize-handle.tsx)
 * own DOM and React state, this file owns the numbers so they can be unit
 * tested. The page and the chat modal share one stored preference.
 */

/** localStorage key, shared by the /lineage page and the chat modal. */
export const INSPECTOR_WIDTH_KEY = "sp:lineage-inspector-width";

/** Narrowest useful inspector. */
export const INSPECTOR_MIN_WIDTH = 320;
/** Canvas that must stay visible left of the inspector. */
export const CANVAS_RESERVE = 240;
/** Width of the left panel once it has collapsed to a rail. */
export const LEFT_RAIL_WIDTH = 36;
/** Default on the page: comfortable for SQL. */
export const PAGE_DEFAULT_WIDTH = 560;
/** Default in the modal: a share of the modal width. */
export const MODAL_DEFAULT_FRACTION = 0.45;
/** The "expand" preset as a share of the container. */
export const WIDE_FRACTION = 0.7;
/** Keyboard steps (px). */
export const KEY_STEP = 32;
export const KEY_STEP_LARGE = 128;

export type InspectorSurface = "page" | "modal";

export interface WidthBounds {
  min: number;
  max: number;
}

/**
 * Bounds for a container this wide. The maximum leaves the canvas reserve
 * plus the collapsed left rail; an unmeasured container (0) is unbounded so
 * the first paint does not snap to the minimum.
 */
export function widthBounds(containerWidth: number): WidthBounds {
  if (!(containerWidth > 0)) return { min: INSPECTOR_MIN_WIDTH, max: Number.POSITIVE_INFINITY };
  const max = Math.max(INSPECTOR_MIN_WIDTH, Math.floor(containerWidth - CANVAS_RESERVE - LEFT_RAIL_WIDTH));
  return { min: INSPECTOR_MIN_WIDTH, max };
}

export function clampWidth(width: number, bounds: WidthBounds): number {
  if (!Number.isFinite(width)) return bounds.min;
  return Math.min(bounds.max, Math.max(bounds.min, Math.round(width)));
}

/**
 * Default width: 560 on the page, 45 percent in the modal, and never so wide
 * that the full left panel would collapse. Only a stored user width may
 * push the panel to its rail.
 */
export function defaultInspectorWidth(
  surface: InspectorSurface,
  containerWidth: number,
  leftPanelWidth = 0,
): number {
  const base =
    surface === "modal" && containerWidth > 0
      ? Math.round(containerWidth * MODAL_DEFAULT_FRACTION)
      : PAGE_DEFAULT_WIDTH;
  if (!(containerWidth > 0)) return base;
  return clampWidth(Math.min(base, containerWidth - leftPanelWidth - CANVAS_RESERVE), widthBounds(containerWidth));
}

export function wideInspectorWidth(containerWidth: number): number {
  return clampWidth(containerWidth * WIDE_FRACTION, widthBounds(containerWidth));
}

/** True when the width already sits at (or past) the wide preset. */
export function isWide(width: number, containerWidth: number): boolean {
  return containerWidth > 0 && width >= wideInspectorWidth(containerWidth) - 4;
}

/**
 * True when the full left panel plus this inspector would squeeze the
 * canvas under the reserve: the panel then collapses to the rail.
 */
export function leftPanelCollapses(containerWidth: number, inspectorWidth: number, panelWidth: number): boolean {
  if (!(containerWidth > 0)) return false;
  return containerWidth - inspectorWidth - panelWidth < CANVAS_RESERVE;
}

/** Widest inspector that still fits the full left panel. */
export function widthFittingPanel(containerWidth: number, panelWidth: number): number {
  return clampWidth(containerWidth - panelWidth - CANVAS_RESERVE, widthBounds(containerWidth));
}

/** Parse a stored preference; null for anything that is not a sane number. */
export function parseStoredWidth(raw: string | null | undefined): number | null {
  if (raw == null) return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < INSPECTOR_MIN_WIDTH) return null;
  return Math.round(n);
}

export function readStoredWidth(storage: Pick<Storage, "getItem"> | null | undefined): number | null {
  try {
    return parseStoredWidth(storage?.getItem(INSPECTOR_WIDTH_KEY));
  } catch {
    return null;
  }
}

export function writeStoredWidth(
  storage: Pick<Storage, "setItem" | "removeItem"> | null | undefined,
  width: number | null,
): void {
  try {
    if (width === null) storage?.removeItem(INSPECTOR_WIDTH_KEY);
    else storage?.setItem(INSPECTOR_WIDTH_KEY, String(Math.round(width)));
  } catch {
    // Private mode or a full store: the width just does not persist.
  }
}

/**
 * Keyboard resize on the separator. Returns the next width, or null when
 * the key is not a resize key. Left widens (the handle is on the left edge,
 * so left moves it left), right narrows.
 */
export function keyboardResize(
  key: string,
  shift: boolean,
  width: number,
  bounds: WidthBounds,
): number | null {
  const step = shift ? KEY_STEP_LARGE : KEY_STEP;
  switch (key) {
    case "ArrowLeft":
      return clampWidth(width + step, bounds);
    case "ArrowRight":
      return clampWidth(width - step, bounds);
    case "Home":
      return bounds.min;
    case "End":
      return Number.isFinite(bounds.max) ? bounds.max : clampWidth(width, bounds);
    default:
      return null;
  }
}
