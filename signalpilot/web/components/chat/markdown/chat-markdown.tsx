"use client";

import { useEffect, useState } from "react";
import {
  defaultRehypePlugins,
  Streamdown,
  type StreamdownProps,
} from "streamdown";
// KaTeX's stylesheet hides the MathML twin it emits for screen readers;
// without it every formula renders twice.
import "katex/dist/katex.min.css";
// Area sheets, loaded in cascade order: base rhythm first, then each surface.
import "./styles/base.css";
import "./styles/typography.css";
import "./styles/containers.css";
import "./styles/code.css";
import "./styles/media.css";
import { MarkdownCode, MarkdownPre } from "./code-block";
import { MarkdownLink } from "./link";

/**
 * Standard HTML elements the GitHub sanitizer schema leaves out. Everything
 * here is ordinary HTML an LLM already writes — no house syntax to teach.
 * `details`, `summary`, `kbd`, `sub`, `sup`, `dl`, and the table elements are
 * already in the base schema.
 */
const EXTRA_TAGS: Record<string, string[]> = {
  abbr: ["title"],
  caption: [],
  figcaption: [],
  figure: [],
  mark: [],
  small: [],
  time: ["datetime"],
  u: [],
  // Spanning cells: a hand-written HTML table is the only way to express a
  // grouped header, and the base schema drops the attributes that make it one.
  td: ["colSpan", "rowSpan", "align"],
  th: ["colSpan", "rowSpan", "align", "scope"],
};

type SanitizeSchema = {
  tagNames?: string[];
  attributes?: Record<string, unknown>;
};

/**
 * Streamdown's own raw → sanitize → harden chain, with those extra tags added
 * to the allowlist. Rebuilding the chain (rather than passing `allowedTags`)
 * keeps markdown inside an HTML block parsed as markdown, which is how GitHub
 * renders a `<details>` body.
 */
const REHYPE_PLUGINS: NonNullable<StreamdownProps["rehypePlugins"]> = (() => {
  const [sanitizePlugin, schema] = defaultRehypePlugins.sanitize as [
    unknown,
    SanitizeSchema,
  ];
  const extended: SanitizeSchema = {
    ...schema,
    tagNames: [...(schema.tagNames ?? []), ...Object.keys(EXTRA_TAGS)],
    attributes: { ...schema.attributes, ...EXTRA_TAGS },
  };
  return [
    defaultRehypePlugins.raw,
    [sanitizePlugin, extended],
    defaultRehypePlugins.harden,
  ] as NonNullable<StreamdownProps["rehypePlugins"]>;
})();

const COMPONENTS = {
  a: MarkdownLink,
  code: MarkdownCode,
  pre: MarkdownPre,
} as StreamdownProps["components"];

// KaTeX is ~264 KB. The first render works without it; the block re-renders
// with typeset math once the plugin lands.
let mathPluginCache: StreamdownProps["plugins"] | undefined;

function useMathPlugin(): StreamdownProps["plugins"] {
  const [plugins, setPlugins] = useState(mathPluginCache);
  useEffect(() => {
    if (mathPluginCache) return;
    let active = true;
    void import("@streamdown/math")
      .then((module) => {
        // Single-dollar inline math stays off: this chat is full of dollar
        // amounts, and `$1,200 … $4,100` would typeset as a formula.
        mathPluginCache = { math: module.math };
        if (active) setPlugins(mathPluginCache);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  return plugins;
}

/**
 * Rendered markdown for every chat surface. Streamdown gives GFM, raw HTML,
 * math, and streaming-safe repair of half-written syntax; the overrides add
 * code highlighting, mermaid, and in-app links.
 *
 * `streaming` keeps partial syntax from flickering mid-run; pass false for
 * content that is already final.
 */
export function ChatMarkdown({
  markdown,
  className = "",
  streaming = false,
}: {
  markdown: string;
  className?: string;
  streaming?: boolean;
}) {
  const plugins = useMathPlugin();
  return (
    <Streamdown
      className={`chat-markdown ${className}`.trim()}
      mode={streaming ? "streaming" : "static"}
      components={COMPONENTS}
      rehypePlugins={REHYPE_PLUGINS}
      plugins={plugins}
      controls={{ table: true, code: false, mermaid: false }}
    >
      {markdown}
    </Streamdown>
  );
}
