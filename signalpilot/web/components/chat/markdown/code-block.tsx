"use client";

// The `code` element override. Fenced blocks render as highlighted code with a
// copy button; ```mermaid renders as a diagram; ```diff gets line tinting.
//
// Presentation lives in `styles/code.css`. This file decides structure only:
// the frame shell, the header band, the scroll body, and the diff line model.

import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import { useIsCodeFenceIncomplete } from "streamdown";
import {
  ChatCode,
  CopyButton,
  type ChatCodeLanguage,
} from "~/components/chat/chat-code";
import { childText, str } from "./attrs";
import { FenceSkeleton, MermaidFence } from "./fence-renderers";

const LANGUAGE_ALIASES: Record<string, ChatCodeLanguage> = {
  sql: "sql",
  postgresql: "sql",
  mysql: "sql",
  duckdb: "sql",
  snowflake: "sql",
  python: "python",
  py: "python",
  bash: "bash",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
};

function codeLanguage(language: string): ChatCodeLanguage {
  return LANGUAGE_ALIASES[language] ?? "text";
}

/**
 * Marks which edges of the scrolling body still have content behind them, so
 * the height cap and the horizontal overflow read as "there is more" rather
 * than as a clipped block. The flags drive gradient shades in `code.css`.
 */
function ScrollBody({ children }: { children: ReactNode }) {
  const host = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState("");

  useEffect(() => {
    const scroller = host.current?.querySelector("pre");
    if (!scroller) return;
    const update = () => {
      const top = scroller.scrollTop > 1;
      const bottom =
        scroller.scrollTop + scroller.clientHeight < scroller.scrollHeight - 1;
      const right =
        scroller.scrollLeft + scroller.clientWidth < scroller.scrollWidth - 1;
      setEdges(
        [top ? "top" : "", bottom ? "bottom" : "", right ? "right" : ""]
          .filter(Boolean)
          .join(" "),
      );
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    // The pre is height-capped, so watch the content too: streaming grows the
    // code element without ever resizing the scroller.
    const observer = new ResizeObserver(update);
    observer.observe(scroller);
    const content = scroller.firstElementChild;
    if (content) observer.observe(content);
    return () => {
      scroller.removeEventListener("scroll", update);
      observer.disconnect();
    };
  }, []);

  return (
    <div ref={host} className="chat-md-code-body" data-edges={edges}>
      {children}
      {/* Vertical shades are pseudo-elements; the horizontal one needs a real
          node because both pseudos are already spoken for. */}
      <span aria-hidden="true" className="chat-md-code-fade-x" />
    </div>
  );
}

type DiffKind = "add" | "del" | "meta" | "hunk" | "ctx";

function diffKind(line: string): DiffKind {
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("diff ") || line.startsWith("index ")) return "meta";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "ctx";
}

/** Renders a unified diff: a sign gutter, tinted rows, `@@` hunks as chrome. */
function DiffBlock({ source }: { source: string }) {
  return (
    <pre className="chat-code chat-md-diff">
      <code>
        {source.split("\n").map((line, index) => {
          const kind = diffKind(line);
          const signed = kind === "add" || kind === "del";
          return (
            <span
              key={index}
              className="chat-md-diff-line"
              data-kind={kind}
            >
              <span aria-hidden="true" className="chat-md-diff-sign">
                {signed ? line.slice(0, 1) : ""}
              </span>
              <span className="chat-md-diff-text">
                {/* Strip the marker column: the gutter carries it now, and
                    context lines keep their own indentation aligned with the
                    added and removed rows. */}
                {(signed || (kind === "ctx" && line.startsWith(" "))
                  ? line.slice(1)
                  : line) || " "}
              </span>
            </span>
          );
        })}
      </code>
    </pre>
  );
}

function CodeFrame({
  language,
  title,
  source,
  children,
}: {
  language: string;
  title: string;
  source: string;
  children: ReactNode;
}) {
  const label = title || language || "text";
  return (
    <div className="chat-md-code" data-lang={language || "text"}>
      <div className="chat-md-code-head">
        <span className="chat-md-code-label" title={label}>
          {label}
        </span>
        {title && language ? (
          <span className="chat-md-code-lang">{language}</span>
        ) : null}
        <span className="chat-md-code-copy">
          <CopyButton text={source} />
        </span>
      </div>
      <ScrollBody>{children}</ScrollBody>
    </div>
  );
}

type CodeProps = ComponentProps<"code"> & {
  node?: unknown;
  metastring?: unknown;
};

export function MarkdownCode({ children, className = "", ...props }: CodeProps) {
  const incomplete = useIsCodeFenceIncomplete();
  const match = /language-([\w.+-]+)/.exec(className);
  const source = childText(children);
  if (!match && !source.includes("\n")) {
    return <code className={className || undefined}>{children}</code>;
  }
  const language = (match?.[1] ?? "").toLowerCase();
  const body = source.replace(/\n$/, "");

  if (language === "mermaid") {
    return incomplete ? (
      <FenceSkeleton label="Diagram streaming…" />
    ) : (
      <MermaidFence source={body} />
    );
  }

  // ```sql title="monthly revenue" — the metastring convention shared by
  // Shiki, Docusaurus, and most markdown pipelines.
  const meta = str(props.metastring);
  const title = /title="([^"]+)"/.exec(meta)?.[1] ?? "";
  if (language === "diff") {
    return (
      <CodeFrame language="diff" title={title} source={body}>
        <DiffBlock source={body} />
      </CodeFrame>
    );
  }
  return (
    <CodeFrame language={language} title={title} source={body}>
      <ChatCode code={body} language={codeLanguage(language)} />
    </CodeFrame>
  );
}

/**
 * Fenced code arrives wrapped in a `pre`; the frame comes from `MarkdownCode`,
 * so this only has to get out of the way.
 */
export function MarkdownPre({ children }: ComponentProps<"pre">) {
  return <>{children}</>;
}
