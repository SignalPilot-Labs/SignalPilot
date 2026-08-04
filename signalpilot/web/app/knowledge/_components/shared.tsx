import type { KnowledgeDoc } from "~/lib/types";
import { CATEGORY_META, catTint } from "./categories";
import { KbIcon } from "./icons";

/** Tinted rounded square holding a category's icon. */
export function CatBox({
  category,
  size = 24,
  iconSize = 14,
}: {
  category: KnowledgeDoc["category"];
  size?: number;
  iconSize?: number;
}) {
  const m = CATEGORY_META[category];
  return (
    <span className="kb-catbox" style={{ width: size, height: size, background: catTint(m.color), color: m.color }}>
      <KbIcon name={m.icon} size={iconSize} />
    </span>
  );
}

/** Short plain-text preview. Prefers the server-computed excerpt (list rows omit body). */
export function snippet(d: KnowledgeDoc): string {
  if (!d.body && d.excerpt) return d.excerpt;
  return (d.body ?? "")
    .replace(/^#\s.*\n?/, "")
    .replace(/```[\s\S]*?```/g, "")
    .replace(/\|.*\|/g, "")
    .replace(/[#>*`-]/g, "")
    .replace(/\[\[([a-z0-9-]+)\]\]/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 130);
}

/** Relative "Nd ago" from a unix-seconds timestamp. */
export function daysAgo(unixSeconds: number): string {
  const d = Math.max(0, Math.floor(Date.now() / 1000 - unixSeconds) / 86400);
  const n = Math.floor(d);
  return n === 0 ? "today" : `${n}d ago`;
}

/** Folder-style path for a doc. */
export function docPath(d: KnowledgeDoc): string {
  if (d.scope === "org") return `org / ${d.category}`;
  return `${d.scope_ref ?? d.scope} / ${d.category}`;
}

/** Short scope label for a row: "org", or the project/connection name. */
export function scopeLabel(d: KnowledgeDoc): string {
  return d.scope === "org" ? "org" : (d.scope_ref ?? d.scope);
}
