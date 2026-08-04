"use client";

import type { ReactNode } from "react";
import type { KnowledgeDoc } from "~/lib/types";
import { CATEGORY_META, catTint } from "./categories";
import { KbIcon } from "./icons";

// ── helpers ───────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// SAFE_URL anchors the external-link allowlist. DO NOT broaden to javascript:/data:/etc.
const SAFE_URL = /^https?:\/\//;

const CATEGORY_PRIORITY: KnowledgeDoc["category"][] = [
  "context", "decisions", "rules", "troubleshooting",
];

export function resolveWikilink(target: string, docs: KnowledgeDoc[]): KnowledgeDoc | null {
  const trimmed = target.trim();
  if (!trimmed) return null;
  let catRaw: string | null = null;
  let titleRaw: string;
  const slashIdx = trimmed.indexOf("/");
  if (slashIdx !== -1) {
    catRaw = trimmed.slice(0, slashIdx).toLowerCase();
    titleRaw = trimmed.slice(slashIdx + 1).toLowerCase();
  } else {
    titleRaw = trimmed.toLowerCase();
  }
  const candidates = docs.filter((doc) => {
    if (doc.status !== "active") return false;
    if (catRaw !== null && doc.category.toLowerCase() !== catRaw) return false;
    return doc.title.toLowerCase() === titleRaw;
  });
  if (candidates.length === 0) return null;
  if (candidates.length === 1) return candidates[0];
  const sorted = candidates.slice().sort((a, b) => {
    const ai = CATEGORY_PRIORITY.indexOf(a.category);
    const bi = CATEGORY_PRIORITY.indexOf(b.category);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
  return sorted[0];
}

type RenderCtx = { docs: KnowledgeDoc[]; onNavigate: (id: string) => void };

function renderInline(text: string, keyPrefix: string, ctx: RenderCtx): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern =
    /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[\[[^\]\n]+\]\])|(\[[^\]]+\]\([^)]+\))|(_(?=\S)([^_]+?)(?<=\S)_)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let idx = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const k = `${keyPrefix}-${idx++}`;
    const [full] = match;
    if (full.startsWith("`")) {
      nodes.push(<code key={k}>{full.slice(1, -1)}</code>);
    } else if (full.startsWith("**")) {
      nodes.push(<strong key={k}>{renderInline(full.slice(2, -2), k, ctx)}</strong>);
    } else if (full.startsWith("*")) {
      nodes.push(<em key={k}>{renderInline(full.slice(1, -1), k, ctx)}</em>);
    } else if (full.startsWith("[[")) {
      const inner = full.slice(2, -2);
      const resolved = resolveWikilink(inner, ctx.docs);
      if (resolved) {
        nodes.push(
          <button
            key={k}
            type="button"
            className="kb-wikilink"
            onClick={() => ctx.onNavigate(resolved.id)}
            title={`${resolved.category}/${resolved.title}`}
          >
            {inner}
          </button>,
        );
      } else {
        nodes.push(
          <span key={k} className="kb-broken" title="broken link — no matching doc">
            {`[[${inner}]]`}
          </span>,
        );
      }
    } else if (full.startsWith("_")) {
      nodes.push(<em key={k}>{renderInline(full.replace(/^_|_$/g, ""), k, ctx)}</em>);
    } else if (full.startsWith("[")) {
      const m = full.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (m && SAFE_URL.test(m[2])) {
        nodes.push(
          <a key={k} href={m[2]} target="_blank" rel="noopener noreferrer">
            {m[1]}
          </a>,
        );
      } else {
        nodes.push(full);
      }
    } else {
      nodes.push(full);
    }
    last = match.index + full.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function renderMarkdown(src: string, ctx: RenderCtx): ReactNode[] {
  const lines = src.split("\n");
  const out: ReactNode[] = [];
  let i = 0;
  let para: string[] = [];
  let counter = 0;
  const key = () => `md-${counter++}`;
  const flushPara = () => {
    if (para.length === 0) return;
    const k = key();
    out.push(<p key={k}>{renderInline(para.join(" "), k, ctx)}</p>);
    para = [];
  };
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      flushPara();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) { codeLines.push(lines[i]); i++; }
      out.push(<pre key={key()}><code>{codeLines.join("\n")}</code></pre>);
      i++;
      continue;
    }
    if (line.startsWith("### ")) { flushPara(); const k = key(); out.push(<h3 key={k}>{renderInline(line.slice(4), k, ctx)}</h3>); i++; continue; }
    if (line.startsWith("## ")) { flushPara(); const k = key(); out.push(<h2 key={k}>{renderInline(line.slice(3), k, ctx)}</h2>); i++; continue; }
    if (line.startsWith("# ")) { flushPara(); const k = key(); out.push(<h1 key={k}>{renderInline(line.slice(2), k, ctx)}</h1>); i++; continue; }
    if (/^[-*] /.test(line)) {
      flushPara();
      const items: ReactNode[] = [];
      while (i < lines.length && /^[-*] /.test(lines[i])) { const ik = key(); items.push(<li key={ik}>{renderInline(lines[i].slice(2), ik, ctx)}</li>); i++; }
      out.push(<ul key={key()}>{items}</ul>);
      continue;
    }
    if (/^\d+\. /.test(line)) {
      flushPara();
      const items: ReactNode[] = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) { const ik = key(); items.push(<li key={ik}>{renderInline(lines[i].replace(/^\d+\. /, ""), ik, ctx)}</li>); i++; }
      out.push(<ol key={key()}>{items}</ol>);
      continue;
    }
    if (line.trim() === "") { flushPara(); i++; continue; }
    para.push(line);
    i++;
  }
  flushPara();
  return out;
}

// ── component ─────────────────────────────────────────────────────────────────

export function DocumentView({
  doc,
  docs,
  backlinks,
  onNavigate,
}: {
  doc: KnowledgeDoc;
  docs: KnowledgeDoc[];
  backlinks: KnowledgeDoc[];
  onNavigate: (id: string) => void;
}) {
  const meta = CATEGORY_META[doc.category];
  return (
    <div className="kb-doc-scroll flex-1 overflow-y-auto">
      <article className="kb-document">
        <header className="kb-doc-head">
          <div className="kb-doc-badges">
            <span
              className="kb-badge"
              style={{ color: meta.color, background: catTint(meta.color), borderColor: "transparent" }}
            >
              <KbIcon name={meta.icon} size={13} />
              {meta.label}
            </span>
            <span className="kb-badge">
              {doc.scope}
              {doc.scope_ref ? `: ${doc.scope_ref}` : ""}
            </span>
            {doc.status !== "active" && (
              <span
                className="kb-badge"
                style={
                  doc.status === "pending"
                    ? { color: "var(--color-warning)", borderColor: "color-mix(in srgb, var(--color-warning) 40%, transparent)" }
                    : undefined
                }
              >
                {doc.status}
              </span>
            )}
          </div>
          <h1 className="kb-doc-title">{doc.title}</h1>
          <div className="kb-doc-meta">
            <span title="times pulled into agent context via MCP">
              <b>{doc.view_count}</b> pulls
            </span>
            <span>
              <b>{backlinks.length}</b> backlinks
            </span>
            <span>{formatBytes(doc.bytes)}</span>
          </div>
        </header>

        <div className="kb-doc-body">
          <div className="kb-prose">
            {doc.body ? (
              renderMarkdown(doc.body, { docs, onNavigate })
            ) : (
              <span className="kb-broken">— no content —</span>
            )}
          </div>

          {backlinks.length > 0 && (
            <div className="kb-backlinks">
              <h4>backlinks · {backlinks.length}</h4>
              {backlinks.map((src) => {
                const m = CATEGORY_META[src.category];
                return (
                  <button
                    key={src.id}
                    type="button"
                    className="kb-backlink"
                    onClick={() => onNavigate(src.id)}
                    title={`${src.category}/${src.title}`}
                  >
                    <span className="kb-catdot" style={{ background: m.color }} />
                    <span className="kb-bt">{src.title}</span>
                    <span className="kb-bm">{m.label}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </article>
    </div>
  );
}
