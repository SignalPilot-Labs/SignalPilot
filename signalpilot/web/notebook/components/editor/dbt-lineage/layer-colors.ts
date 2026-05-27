import type { DbtModelLayer } from "./types";

export interface LayerTheme {
  bg: string;
  border: string;
  headerBg: string;
  headerText: string;
  accent: string;
  badge: string;
  badgeText: string;
  glow: string;
}

export const LAYER_THEMES: Record<DbtModelLayer, LayerTheme> = {
  seed: {
    bg: "bg-amber-950/30",
    border: "border-amber-700/50",
    headerBg: "bg-amber-900/60",
    headerText: "text-amber-200",
    accent: "text-amber-400",
    badge: "bg-amber-800/60",
    badgeText: "text-amber-300",
    glow: "shadow-amber-900/30",
  },
  staging: {
    bg: "bg-sky-950/30",
    border: "border-sky-700/50",
    headerBg: "bg-sky-900/60",
    headerText: "text-sky-200",
    accent: "text-sky-400",
    badge: "bg-sky-800/60",
    badgeText: "text-sky-300",
    glow: "shadow-sky-900/30",
  },
  intermediate: {
    bg: "bg-slate-900/40",
    border: "border-slate-600/50",
    headerBg: "bg-slate-800/60",
    headerText: "text-slate-200",
    accent: "text-slate-400",
    badge: "bg-slate-700/60",
    badgeText: "text-slate-300",
    glow: "shadow-slate-800/30",
  },
  dimension: {
    bg: "bg-violet-950/30",
    border: "border-violet-600/50",
    headerBg: "bg-violet-900/60",
    headerText: "text-violet-200",
    accent: "text-violet-400",
    badge: "bg-violet-800/60",
    badgeText: "text-violet-300",
    glow: "shadow-violet-900/30",
  },
  fact: {
    bg: "bg-emerald-950/30",
    border: "border-emerald-600/50",
    headerBg: "bg-emerald-900/60",
    headerText: "text-emerald-200",
    accent: "text-emerald-400",
    badge: "bg-emerald-800/60",
    badgeText: "text-emerald-300",
    glow: "shadow-emerald-900/30",
  },
  mart: {
    bg: "bg-rose-950/30",
    border: "border-rose-600/50",
    headerBg: "bg-rose-900/60",
    headerText: "text-rose-200",
    accent: "text-rose-400",
    badge: "bg-rose-800/60",
    badgeText: "text-rose-300",
    glow: "shadow-rose-900/30",
  },
  other: {
    bg: "bg-zinc-900/40",
    border: "border-zinc-600/50",
    headerBg: "bg-zinc-800/60",
    headerText: "text-zinc-200",
    accent: "text-zinc-400",
    badge: "bg-zinc-700/60",
    badgeText: "text-zinc-300",
    glow: "shadow-zinc-800/30",
  },
};

export const LAYER_LABELS: Record<DbtModelLayer, string> = {
  seed: "Seed",
  staging: "Staging",
  intermediate: "Intermediate",
  dimension: "Dimension",
  fact: "Fact",
  mart: "Mart",
  other: "Other",
};

export const MATERIALIZATION_ICONS: Record<string, string> = {
  table: "T",
  view: "V",
  incremental: "I",
  ephemeral: "E",
  seed: "S",
  source: "X",
  snapshot: "N",
};

export const EDGE_COLORS: Record<DbtModelLayer, string> = {
  seed: "#d97706",
  staging: "#0284c7",
  intermediate: "#64748b",
  dimension: "#7c3aed",
  fact: "#059669",
  mart: "#e11d48",
  other: "#71717a",
};
