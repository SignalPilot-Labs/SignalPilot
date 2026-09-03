"use client";

export {
  CardFrame,
  CountUp,
  ErrorBanner,
  InputPills,
  KindIcon,
  ProgressRail,
  RawResultTab,
  SkeletonRows,
  StatPill,
  prefersReducedMotion,
  typeDot,
} from "./card-primitives";
export {
  GENERIC_CARD_KINDS,
  getToolCardDefinition,
  registerToolCard,
  registeredToolCardKinds,
  resolveToolCard,
  type ToolCardAccent,
  type ToolCardContext,
  type ToolCardDefinition,
  type ToolCardKind,
  type ToolCardSummary,
} from "./registry";
export {
  ACCENT_BY_KIND,
  ICON_BY_KIND,
  NOUN_BY_KIND,
  accentForKind,
  cardKindForStep,
  iconForKind,
} from "./registry-tools";
export { ToolCard } from "./tool-card";
export {
  ChipPill,
  MAX_STRIP_CHIPS,
  ToolChip,
  ToolChipStrip,
  chipForStep,
  mergeChips,
  parseStat,
  type ChipModel,
} from "./tool-chip";
export {
  COMPLETION_HOLD_MS,
  useCardDensity,
  type CardDensity,
  type CardDensityOptions,
  type CardDensityState,
} from "./use-card-density";
