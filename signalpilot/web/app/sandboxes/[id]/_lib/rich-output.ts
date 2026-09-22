/** Sandbox output parsing: rich HTML/image extraction with a strict sanitizer. */

import DOMPurify, { type Config as DOMPurifyConfig } from "dompurify";

export interface HistoryEntry {
  type: "input" | "output" | "error" | "system" | "image" | "html";
  text: string;
  timestamp: number;
  execution_ms?: number;
  imageData?: string;
  htmlContent?: string;
}

// Configure DOMPurify with strict allowlist
const PURIFY_CONFIG: DOMPurifyConfig = {
  ALLOWED_TAGS: ["table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col", "br", "span", "div", "p", "pre", "code"],
  ALLOWED_ATTR: ["colspan", "rowspan", "class", "scope"],
  FORBID_ATTR: ["style", "id", "onclick", "onerror", "onload", "onmouseover"],
};

export function sanitizeTableHtml(html: string): string {
  return DOMPurify.sanitize(html, PURIFY_CONFIG);
}

export function extractRichOutput(output: string): {
  text: string;
  images: string[];
  html: string | null;
} {
  const images: string[] = [];
  let html: string | null = null;
  let text = output;

  const imgRegex = /data:image\/(png|jpeg|svg\+xml);base64,[A-Za-z0-9+/=]+/g;
  let match;
  while ((match = imgRegex.exec(output)) !== null) {
    images.push(match[0]);
    text = text.replace(match[0], `[Image ${images.length}]`);
  }

  const htmlTableMatch = output.match(/<table[\s\S]*?<\/table>/i);
  if (htmlTableMatch) {
    html = sanitizeTableHtml(htmlTableMatch[0]);
    text = text.replace(htmlTableMatch[0], "[HTML Table]");
  }

  return { text: text.trim(), images, html };
}
