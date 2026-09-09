/**
 * Turns streamed markdown into short plain-text fragments for the thoughts
 * ticker. Code fences, tables, headings and rules never read well at two
 * lines, so they are dropped rather than clipped.
 */

export const MAX_THOUGHTS = 3;
const MIN_FRAGMENT_CHARS = 8;

/** A fragment with a stable id (its index in the stream) so a growing tail row keeps its identity. */
export type Thought = { id: number; text: string };

export function stripMarkdown(markdown: string): string {
  const withoutFences = markdown.replace(/```[\s\S]*?```/g, " ").replace(/```[\s\S]*$/g, " ");
  const lines = withoutFences.split(/\r?\n/).filter((line) => {
    const trimmed = line.trim();
    if (!trimmed) return false;
    if (/^\|/.test(trimmed) || /^[-*_]{3,}$/.test(trimmed)) return false;
    if (/^#{1,6}\s/.test(trimmed)) return false;
    return true;
  });
  return lines
    .map((line) =>
      line
        .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
        .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
        .replace(/`([^`]*)`/g, "$1")
        .replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "")
        .replace(/^\s*>\s?/, "")
        // Emphasis markers only at word edges, so snake_case identifiers survive.
        .replace(/(?<![\w*_])(\*\*|__)(?=\S)(.+?)(?<=\S)\1(?![\w*_])/g, "$2")
        .replace(/(?<![\w*_])(\*|_)(?=\S)(.+?)(?<=\S)\1(?![\w*_])/g, "$2")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .filter(Boolean)
    .join("\n");
}

export function splitFragments(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+|\n+/)
    .map((part) => part.trim())
    .filter((part) => part.length >= MIN_FRAGMENT_CHARS && /[a-z0-9]/i.test(part));
}

/** The last `MAX_THOUGHTS` fragments of the streamed text, ids counted from the stream start. */
export function recentThoughts(markdown: string): Thought[] {
  const fragments = splitFragments(stripMarkdown(markdown));
  const start = Math.max(0, fragments.length - MAX_THOUGHTS);
  return fragments.slice(start).map((text, index) => ({ id: start + index, text }));
}

/** First readable line of a final answer, sized for the Now slot. */
export function headlineFrom(markdown: string, max = 120): string | null {
  const first = splitFragments(stripMarkdown(markdown))[0];
  if (!first) return null;
  return first.length > max ? `${first.slice(0, max - 1).trimEnd()}…` : first;
}
