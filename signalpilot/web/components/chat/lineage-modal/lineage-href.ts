/**
 * Parse the agent's lineage deep links:
 *   /lineage/<model>?project=<id>
 *   /lineage/<model>/raw?project=<id>
 *
 * Only a root-relative href with a `project` query param opens the in-chat
 * modal. Anything else (no project, a nested path, an absolute URL) stays a
 * normal navigation.
 */

export interface LineageHref {
  modelName: string;
  projectId: string;
  raw: boolean;
  href: string;
}

const LINEAGE_RE = /^\/lineage\/([^/?#]+)(\/raw)?\/?(?:\?([^#]*))?(?:#.*)?$/i;

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export function parseLineageHref(href: string | undefined): LineageHref | null {
  if (!href) return null;
  const match = LINEAGE_RE.exec(href);
  if (!match) return null;
  const [, model, rawSegment, query] = match;
  const projectId = query ? new URLSearchParams(query).get("project") : null;
  if (!projectId) return null;
  const modelName = decode(model);
  if (!modelName || modelName.toLowerCase() === "raw") return null;
  return { modelName, projectId, raw: Boolean(rawSegment), href };
}

/** True for a plain left click: no modifier key, not the middle button. */
export function isPlainLeftClick(event: {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  defaultPrevented: boolean;
}): boolean {
  return (
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey &&
    !event.defaultPrevented
  );
}
