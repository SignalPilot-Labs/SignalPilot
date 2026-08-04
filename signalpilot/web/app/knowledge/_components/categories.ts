/* Single source of truth for category presentation: label, color, icon, description.
   Colors reference the scoped --kb-* vars defined in knowledge.css.

   The four buckets:
     context         — the "God Doc": always loaded into every agent (like CLAUDE.md)
     decisions       — what the project does and why models are built this way
     rules           — how to write models here + business rules in the data
     troubleshooting — known errors, fixes, and database-specific quirks
*/
import type { KnowledgeDoc } from "~/lib/types";

export type CategoryMeta = { label: string; color: string; icon: string; description: string };

export const CATEGORY_META: Record<KnowledgeDoc["category"], CategoryMeta> = {
  context: {
    label: "Context",
    color: "var(--kb-context)",
    icon: "compass",
    description: "Always loaded into every agent — the shared brief for this org or project (like CLAUDE.md).",
  },
  decisions: {
    label: "Agent Decisions",
    color: "var(--kb-decisions)",
    icon: "bulb",
    description: "What the project does and why models are built this way — grain, joins, filters, and the reasoning behind them.",
  },
  rules: {
    label: "Rules",
    color: "var(--kb-rules)",
    icon: "scale",
    description: "How to write models here, plus the business rules encoded in the data.",
  },
  troubleshooting: {
    label: "Troubleshooting",
    color: "var(--kb-troubleshooting)",
    icon: "wrench",
    description: "Known errors, fixes, and database-specific quirks the team has hit before.",
  },
};

/** Display order for categories across the UI. */
export const CATEGORY_ORDER: KnowledgeDoc["category"][] = ["context", "decisions", "rules", "troubleshooting"];

/** The always-loaded "God Doc" category, pinned separately in the UI. */
export const GOD_DOC_CATEGORY: KnowledgeDoc["category"] = "context";

/** The on-demand categories (everything except the God Doc). */
export const BROWSE_CATEGORIES: KnowledgeDoc["category"][] = ["decisions", "rules", "troubleshooting"];

/** A faint tinted background for a category color (for icon chips / badges). */
export function catTint(color: string, pct = 16): string {
  return `color-mix(in srgb, ${color} ${pct}%, transparent)`;
}

/** Enforced scope × category matrix (mirrors gateway models/knowledge.py). */
export const SCOPE_CATEGORIES: Record<KnowledgeDoc["scope"], KnowledgeDoc["category"][]> = {
  org: ["context", "decisions", "rules"],
  project: ["context", "decisions", "rules", "troubleshooting"],
  connection: ["context", "troubleshooting"],
};
