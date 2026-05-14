/**
 * Utility helpers for notebook cell rendering.
 * Kept separate to keep notebook-cell.tsx lean.
 */

import type { Config as DOMPurifyConfig } from "dompurify";

// ─── ANSI stripping ────────────────────────────────────────────────────────────

/** Strips ANSI CSI and OSC escape sequences from terminal output. */
export function stripAnsi(text: string): string {
  // Strip CSI sequences: ESC [ ... letter  (e.g., color codes)
  let out = text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "");
  // Strip OSC sequences: ESC ] ... (BEL or ST)
  out = out.replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g, "");
  return out;
}

// ─── DOMPurify configs ─────────────────────────────────────────────────────────

/**
 * Config for rich HTML notebook outputs (DataFrames, HTML widgets).
 * Allows common formatting tags; forbids all event handlers and style attrs.
 */
export const NOTEBOOK_HTML_PURIFY_CONFIG: DOMPurifyConfig = {
  ALLOWED_TAGS: [
    "p", "div", "span", "br",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "code", "blockquote",
    "ul", "ol", "li",
    "em", "strong", "s", "del", "ins",
    "a", "img",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
  ],
  ALLOWED_ATTR: [
    "href", "src", "alt", "title",
    "class", "colspan", "rowspan", "scope",
    "width", "height",
  ],
  FORBID_ATTR: ["style", "id", "onclick", "onerror", "onload", "onmouseover"],
  ALLOW_DATA_ATTR: false,
};

/**
 * Config for markdown-rendered HTML.
 * Slightly broader than notebook HTML to support prose formatting.
 */
export const MARKDOWN_PURIFY_CONFIG: DOMPurifyConfig = {
  ALLOWED_TAGS: [
    "p", "div", "span", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "code", "blockquote",
    "ul", "ol", "li",
    "em", "strong", "s", "del", "ins",
    "a", "img",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
  ],
  ALLOWED_ATTR: [
    "href", "src", "alt", "title", "class",
    "colspan", "rowspan", "scope",
  ],
  FORBID_ATTR: ["style", "id", "onclick", "onerror", "onload"],
  ALLOW_DATA_ATTR: false,
};

// ─── MIME helpers ──────────────────────────────────────────────────────────────

/**
 * Returns true if the string looks like raw SVG XML (starts with < after whitespace).
 */
export function isRawSvg(value: string): boolean {
  return value.trimStart().startsWith("<");
}

/**
 * Encodes a raw SVG string to a base64 data URI suitable for an <img> src.
 * This sandboxes the SVG in the img element's security context.
 */
export function svgToDataUri(rawSvg: string): string {
  // btoa works on ASCII/latin1; use encodeURIComponent for unicode safety
  try {
    return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(rawSvg)))}`;
  } catch {
    // Fallback: percent-encode for unicode if btoa fails
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(rawSvg)}`;
  }
}

/**
 * Joins a MIME value that may be a string or string array into a single string.
 */
export function resolveMimeValue(value: string | string[]): string {
  return Array.isArray(value) ? value.join("") : value;
}
