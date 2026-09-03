"use client";

// Fenced blocks that render as something other than code. Only ```mermaid
// qualifies: it is the one diagram syntax models already write unprompted.
//
// Structure only. Presentation lives in `styles/media.css`, so a diagram frame,
// its streaming placeholder and its error card all share the framed-block shell
// used by code and tables.

import { AlertTriangle } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

/** First keyword of a mermaid source → the label on the frame header. */
const DIAGRAM_LABELS: Record<string, string> = {
  flowchart: "flowchart",
  graph: "flowchart",
  sequencediagram: "sequence",
  classdiagram: "class diagram",
  statediagram: "state diagram",
  "statediagram-v2": "state diagram",
  erdiagram: "entity relations",
  journey: "journey",
  gantt: "gantt",
  pie: "pie",
  mindmap: "mind map",
  timeline: "timeline",
  gitgraph: "git graph",
  quadrantchart: "quadrant",
  "xychart-beta": "chart",
  block: "block diagram",
};

function diagramLabel(source: string): string {
  const head = source.trim().split("\n", 1)[0] ?? "";
  const keyword = head.trim().split(/[\s:{(]/, 1)[0]?.toLowerCase() ?? "";
  return DIAGRAM_LABELS[keyword] ?? "diagram";
}

function DiagramFrame({
  label,
  tone,
  children,
}: {
  label: ReactNode;
  tone?: "warning";
  children: ReactNode;
}) {
  return (
    <div className="chat-md-diagram" data-tone={tone}>
      <div className="chat-md-diagram-head">{label}</div>
      {children}
    </div>
  );
}

/**
 * Shown while the fence is still streaming, and again for the tick between the
 * fence closing and mermaid returning an SVG. It is on screen in every real
 * run, so it holds roughly a diagram's height and shimmers instead of drawing
 * a dashed placeholder box.
 */
export function FenceSkeleton({ label }: { label: string }) {
  return (
    <div className="chat-md-diagram chat-md-diagram-pending" role="status">
      <div className="chat-md-diagram-head">{label}</div>
      <div className="chat-md-diagram-body">
        <div className="chat-md-diagram-ghost" aria-hidden>
          <span className="chat-md-ghost-node" />
          <span className="chat-md-ghost-edge" />
          <span className="chat-md-ghost-node" />
          <span className="chat-md-ghost-edge" />
          <span className="chat-md-ghost-node" />
        </div>
      </div>
    </div>
  );
}

export function FenceError({
  message,
  source,
}: {
  message: string;
  source: string;
}) {
  return (
    <DiagramFrame
      tone="warning"
      label={
        <>
          <AlertTriangle className="chat-md-diagram-icon" aria-hidden />
          <span className="chat-md-diagram-message">{message}</span>
        </>
      }
    >
      <div className="chat-md-diagram-body">
        <pre className="chat-md-diagram-well">
          <code>{source}</code>
        </pre>
      </div>
    </DiagramFrame>
  );
}

let mermaidReady: Promise<typeof import("mermaid").default> | null = null;

function loadMermaid() {
  if (!mermaidReady) {
    mermaidReady = import("mermaid").then((module) => {
      module.default.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "base",
        // The SVG is generated outside React but lives in the document, so the
        // custom properties resolve; the literal stack is the fallback for the
        // hidden element mermaid measures label widths in.
        fontFamily:
          'var(--font-sans), -apple-system, "Segoe UI", system-ui, sans-serif',
        fontSize: 13,
        flowchart: {
          curve: "basis",
          padding: 10,
          nodeSpacing: 38,
          rankSpacing: 46,
          useMaxWidth: true,
        },
        sequence: {
          diagramMarginX: 8,
          diagramMarginY: 8,
          actorMargin: 46,
          width: 104,
          height: 38,
          boxMargin: 8,
          boxTextMargin: 4,
          noteMargin: 8,
          messageMargin: 34,
          useMaxWidth: true,
        },
        themeVariables: {
          darkMode: true,
          background: "#121214",
          // Flowchart nodes: one step above the frame fill so they read as
          // objects on the surface rather than outlined holes in it.
          primaryColor: "#1b1b1e",
          primaryTextColor: "#ededed",
          primaryBorderColor: "rgba(255,255,255,0.16)",
          secondaryColor: "#18181a",
          secondaryTextColor: "#ededed",
          secondaryBorderColor: "rgba(255,255,255,0.12)",
          tertiaryColor: "#101012",
          tertiaryTextColor: "#9c9c96",
          tertiaryBorderColor: "rgba(255,255,255,0.08)",
          nodeBorder: "rgba(255,255,255,0.16)",
          mainBkg: "#1b1b1e",
          nodeTextColor: "#ededed",
          textColor: "#9c9c96",
          titleColor: "#ededed",
          lineColor: "#6f6f6a",
          // Edge labels sit on the line, so they need the frame fill behind
          // them, not the page fill.
          edgeLabelBackground: "#121214",
          clusterBkg: "#101012",
          clusterBorder: "rgba(255,255,255,0.08)",
          // Sequence diagrams read a separate set of variables.
          actorBkg: "#1b1b1e",
          actorBorder: "rgba(255,255,255,0.16)",
          actorTextColor: "#ededed",
          actorLineColor: "rgba(255,255,255,0.14)",
          signalColor: "#8a8a84",
          signalTextColor: "#9c9c96",
          labelBoxBkgColor: "#18181a",
          labelBoxBorderColor: "rgba(255,255,255,0.12)",
          labelTextColor: "#ededed",
          loopTextColor: "#9c9c96",
          activationBkgColor: "#26262a",
          activationBorderColor: "rgba(255,255,255,0.16)",
          noteBkgColor: "#18181a",
          noteBorderColor: "rgba(255,255,255,0.12)",
          noteTextColor: "#ededed",
          sequenceNumberColor: "#0e0e0f",
        },
      });
      return module.default;
    });
  }
  return mermaidReady;
}

/** ```mermaid fences — flowcharts, sequence diagrams, ERDs, Gantt charts. */
export function MermaidFence({ source }: { source: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setError("");
    void loadMermaid()
      .then((mermaid) => mermaid.render(`mmd-${id}`, source))
      .then((result) => {
        if (active) setSvg(result.svg);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(
            cause instanceof Error ? cause.message : "Diagram failed to render.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [id, source]);
  if (error) return <FenceError message={error} source={source} />;
  if (!svg) return <FenceSkeleton label="Rendering diagram…" />;
  return (
    <DiagramFrame label={diagramLabel(source)}>
      <div
        className="chat-md-mermaid chat-md-diagram-body"
        // Mermaid output is SVG it generated itself from the fence source, with
        // securityLevel "strict" (no click handlers, HTML labels escaped).
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </DiagramFrame>
  );
}
