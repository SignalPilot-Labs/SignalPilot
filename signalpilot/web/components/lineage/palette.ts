/**
 * Layer palette for the dbt map — VALIDATED, do not eyeball-edit.
 *
 * The seven hexes are the dark-mode categorical slots of the validated
 * reference palette, assigned to pipeline layers in slot order (the ordering
 * is the CVD-safety mechanism). Checked against surface #141416:
 *   lightness band, chroma floor, adjacent CVD dE >= 8.4, normal-vision
 *   dE >= 19.3, contrast >= 3:1 — ALL PASS.
 * Identity is never color-alone: every node carries its layer label and a
 * materialization glyph.
 */

export type MapLayer =
  | "source"
  | "staging"
  | "intermediate"
  | "dimension"
  | "fact"
  | "mart"
  | "other";

/** Fixed pipeline order — legend, schema panel, and hue assignment all use it. */
export const LAYER_ORDER: MapLayer[] = [
  "source",
  "staging",
  "intermediate",
  "dimension",
  "fact",
  "mart",
  "other",
];

export const LAYER_COLOR: Record<MapLayer, string> = {
  source: "#3987e5", // slot 1 blue
  staging: "#d95926", // slot 2 orange
  intermediate: "#199e70", // slot 3 aqua
  dimension: "#c98500", // slot 4 yellow
  fact: "#d55181", // slot 5 magenta
  mart: "#008300", // slot 6 green
  other: "#9085e9", // slot 7 violet
};

export const LAYER_LABEL: Record<MapLayer, string> = {
  source: "source",
  staging: "staging",
  intermediate: "intermediate",
  dimension: "dimension",
  fact: "fact",
  mart: "mart",
  other: "other",
};

/** Materialization glyphs — the secondary (non-color) identity channel. */
export const MAT_GLYPH: Record<string, string> = {
  table: "▦",
  view: "▢",
  incremental: "◪",
  ephemeral: "◌",
  seed: "⬒",
  source: "⛁",
  snapshot: "⧉",
};

export function matGlyph(materialized: string | null | undefined, layer: MapLayer): string {
  if (layer === "source") return MAT_GLYPH.source;
  return MAT_GLYPH[materialized ?? ""] ?? "▢";
}
