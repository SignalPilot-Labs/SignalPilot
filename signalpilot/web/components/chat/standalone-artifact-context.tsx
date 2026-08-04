import { useLayoutEffect, useRef, useState } from "react";

import type { StandaloneChatArtifact } from "~/lib/api";

type ArtifactContextData = Pick<
  StandaloneChatArtifact,
  "freshness_at" | "assumptions" | "exclusions" | "caveats"
>;

const COLLAPSED_CONTEXT_HEIGHT = 112;

export function StandaloneArtifactContext({
  artifact,
}: {
  artifact: ArtifactContextData;
}) {
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const groups = [
    { label: "Assumptions", values: artifact.assumptions },
    { label: "Exclusions", values: artifact.exclusions },
    { label: "Caveats", values: artifact.caveats },
  ].filter((group) => group.values.length > 0);
  const contentSignature = [
    artifact.freshness_at ?? "",
    ...artifact.assumptions,
    ...artifact.exclusions,
    ...artifact.caveats,
  ].join("\u0000");

  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const updateOverflow = () => {
      const nextOverflowing = content.scrollHeight > COLLAPSED_CONTEXT_HEIGHT;
      setOverflowing(nextOverflowing);
      if (!nextOverflowing) setExpanded(false);
    };
    updateOverflow();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(content);
    return () => observer.disconnect();
  }, [contentSignature]);

  if (!artifact.freshness_at && groups.length === 0) return null;

  const toggleExpanded = () => {
    if (overflowing) setExpanded((value) => !value);
  };

  return (
    <div className="border-t border-[var(--color-border)] px-3 py-2 text-[11px] leading-5 text-[var(--color-text-dim)]">
      <div
        role={overflowing ? "button" : undefined}
        tabIndex={overflowing ? 0 : undefined}
        aria-expanded={overflowing ? expanded : undefined}
        aria-label={
          overflowing
            ? expanded
              ? "Collapse attachment details"
              : "Expand attachment details"
            : undefined
        }
        onClick={toggleExpanded}
        onKeyDown={(event) => {
          if (overflowing && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            toggleExpanded();
          }
        }}
        className={`relative rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-2 transition-[box-shadow,border-color] ${
          overflowing
            ? "cursor-pointer shadow-[0_14px_20px_-16px_rgba(0,0,0,0.85)] hover:border-[var(--color-border-hover)]"
            : ""
        }`}
      >
        <div
          ref={contentRef}
          data-artifact-context-content
          className={`space-y-2 ${
            overflowing && !expanded ? "max-h-28 overflow-hidden" : ""
          }`}
        >
          {artifact.freshness_at && (
            <p>
              Fresh through {new Date(artifact.freshness_at).toLocaleString()}.
            </p>
          )}
          {groups.map((group) => (
            <section key={group.label}>
              <p className="font-medium text-[var(--color-text-muted)]">
                {group.label}
              </p>
              <ul className="list-disc pl-4">
                {group.values.map((value, index) => (
                  <li key={`${index}-${value}`}>{value}</li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        {overflowing && !expanded && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 bottom-0 h-9 rounded-b-lg bg-gradient-to-t from-[var(--color-bg-card)] to-transparent"
          />
        )}
      </div>
    </div>
  );
}
