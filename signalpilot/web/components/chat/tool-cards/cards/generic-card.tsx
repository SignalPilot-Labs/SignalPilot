"use client";

import { useState } from "react";
import { ChatCode } from "~/components/chat/chat-code";
import { GenericInput, StepBody, stepHasBody } from "~/components/chat/run-timeline/step-body";
import type { RunStep } from "~/lib/chat-run-steps";
import { ProgressRail } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * The fallback card for `json`, `text` and `legacy` results — and, until a
 * dedicated card registers, for every other kind too (the registry re-keys
 * this definition). Legacy and unhandled kinds delegate to `StepBody`, so
 * old runs and not-yet-carded tools look exactly as they did.
 */

/** Above this the JSON tree gives way to a plain code block. */
const TREE_MAX_CHARS = 8 * 1024;
const TREE_MAX_CHILDREN = 50;

export function summarizeGeneric(step: RunStep): ToolCardSummary {
  const summary = step.result?.summary ?? null;
  return {
    title: step.title,
    stat: summary && summary !== step.title ? summary : null,
    ok: step.status !== "failed",
  };
}

function InputList({ step }: { step: RunStep }) {
  const entries = Object.entries(step.input ?? {}).filter(
    ([, value]) => value != null && value !== "",
  );
  if (!entries.length) return null;
  return (
    <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 px-3.5 py-3 text-[11px]">
      {entries.slice(0, 8).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-[var(--color-text-dim)]">{key}</dt>
          <dd className="min-w-0 truncate font-mono text-[var(--color-text-muted)]">
            {typeof value === "string" ? value : JSON.stringify(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Primitive({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="italic text-[var(--color-text-dim)]">null</span>;
  }
  if (typeof value === "string") {
    return <span className="text-[var(--color-success)]/85">&quot;{value}&quot;</span>;
  }
  if (typeof value === "number") return <span className="text-[#86b6de]">{value}</span>;
  if (typeof value === "boolean") {
    return <span className="text-[var(--color-warning)]">{String(value)}</span>;
  }
  return <span>{String(value)}</span>;
}

function JsonNode({
  name,
  value,
  depth,
}: {
  name: string | null;
  value: unknown;
  depth: number;
}) {
  const [open, setOpen] = useState(depth < 2);
  const isArray = Array.isArray(value);
  const isObject = value !== null && typeof value === "object";
  const label = name !== null && (
    <span className="text-[var(--color-text-muted)]">{name}: </span>
  );
  if (!isObject) {
    return (
      <div className="leading-5">
        {label}
        <Primitive value={value} />
      </div>
    );
  }
  const entries = isArray
    ? (value as unknown[]).map((item, index) => [String(index), item] as const)
    : Object.entries(value as Record<string, unknown>);
  const shown = entries.slice(0, TREE_MAX_CHILDREN);
  const bracket = isArray ? ["[", "]"] : ["{", "}"];
  return (
    <div className="leading-5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="text-left hover:text-[var(--color-text)]"
      >
        <span className="inline-block w-3 text-[var(--color-text-dim)]">{open ? "▾" : "▸"}</span>
        {label}
        <span className="text-[var(--color-text-dim)]">
          {bracket[0]}
          {!open && ` ${entries.length} ${isArray ? "items" : "keys"} `}
          {!open && bracket[1]}
        </span>
      </button>
      {open && (
        <div className="border-l border-[var(--color-border)] pl-3">
          {shown.map(([key, child]) => (
            <JsonNode key={key} name={isArray ? null : key} value={child} depth={depth + 1} />
          ))}
          {entries.length > shown.length && (
            <div className="text-[var(--color-text-dim)]">
              … {entries.length - shown.length} more
            </div>
          )}
          <span className="text-[var(--color-text-dim)]">{bracket[1]}</span>
        </div>
      )}
    </div>
  );
}

/** Collapsible JSON tree (two levels open); plain code past 8 KB. */
export function JsonTree({ value }: { value: unknown }) {
  let serialized = "";
  try {
    serialized = JSON.stringify(value, null, 2) ?? "";
  } catch {
    serialized = String(value);
  }
  if (serialized.length > TREE_MAX_CHARS) {
    return <ChatCode code={serialized} language="text" maxHeightClass="max-h-72" />;
  }
  return (
    <div
      data-testid="chat-tool-json-tree"
      className="max-h-72 overflow-auto px-3.5 py-3 font-mono text-[11.5px] text-[var(--color-text)]"
    >
      <JsonNode name={null} value={value} depth={0} />
    </div>
  );
}

function LegacyBody({ step }: { step: RunStep }) {
  if (!stepHasBody(step)) return <InputList step={step} />;
  return (
    <div className="p-2">
      <StepBody step={step} />
    </div>
  );
}

export function GenericRunning({ step }: ToolCardContext) {
  if (step.sql || step.code) return <LegacyBody step={step} />;
  return (
    <>
      <div className="p-2">
        <GenericInput step={step} />
      </div>
      <ProgressRail label="Working…" />
    </>
  );
}

export function GenericExpanded({ step, result }: ToolCardContext) {
  if (result?.kind === "json") {
    return (
      <>
        <InputList step={step} />
        <div className="border-t border-[var(--color-border)]">
          <JsonTree value={result.value} />
        </div>
      </>
    );
  }
  if (result?.kind === "text") {
    return (
      <>
        <InputList step={step} />
        {result.resultText && (
          <div className="border-t border-[var(--color-border)]">
            <ChatCode code={result.resultText} language="text" maxHeightClass="max-h-72" />
          </div>
        )}
      </>
    );
  }
  // Legacy, or a projected kind without its own card yet: the old body.
  return <LegacyBody step={step} />;
}

for (const kind of ["json", "text", "legacy"] as const) {
  registerToolCard({
    kind,
    Icon: iconForKind(kind),
    accent: "neutral",
    summarize: summarizeGeneric,
    Running: GenericRunning,
    Expanded: GenericExpanded,
  });
}
