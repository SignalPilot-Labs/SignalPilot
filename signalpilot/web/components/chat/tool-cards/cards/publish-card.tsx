"use client";

import { ExternalLink } from "lucide-react";
import { useContext } from "react";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { DashboardPreviewDetails, StepBody } from "~/components/chat/run-timeline/step-body";
import type { ArtifactResult, RunStep } from "~/lib/chat-run-steps";
import { KindIcon } from "../card-primitives";
import { registerToolCard, type ToolCardContext, type ToolCardSummary } from "../registry";
import { iconForKind } from "../registry-tools";

/**
 * Artifact card: `publish_table` / `publish_chart` / `publish_report`,
 * `start_analysis_notebook` and `create_dashboard_preview`. Deliberately
 * thin: the filename, the kind, any follow-up the tool asked for, and an
 * "Open" button when the conversation's file manifest carries the file.
 * Dashboard previews keep the existing `DashboardPreviewDetails` body.
 */

type ArtifactKind = ArtifactResult["artifactKind"];

const KIND_BY_TOOL: Record<string, ArtifactKind> = {
  publish_table: "table",
  publish_chart: "chart",
  publish_report: "report",
  start_analysis_notebook: "notebook",
  create_dashboard_preview: "dashboard",
};

function artifactResult(step: RunStep): ArtifactResult | null {
  return step.result?.kind === "artifact" ? step.result : null;
}

export function artifactKindForStep(step: RunStep): ArtifactKind | null {
  return artifactResult(step)?.artifactKind ?? KIND_BY_TOOL[step.tool ?? ""] ?? null;
}

function inputString(step: RunStep, key: string): string | null {
  const raw = step.input?.[key];
  return typeof raw === "string" && raw.trim() ? raw.trim() : null;
}

/** The filename (or notebook name) the card is about. */
export function artifactName(step: RunStep): string | null {
  const result = artifactResult(step);
  return (
    result?.filename ??
    result?.notebook ??
    result?.notebookPath ??
    inputString(step, "filename") ??
    inputString(step, "notebook") ??
    inputString(step, "name") ??
    step.file
  );
}

/**
 * Notebook and dashboard steps carry a kind-specific title; publish steps
 * keep the humanized step title ("Published a chart") so transcript copy
 * stays stable, falling back to the kind only when the step has none.
 */
function titleFor(step: RunStep, kind: ArtifactKind | null, published: boolean): string {
  if (kind === "notebook") return "Notebook started";
  if (kind === "dashboard") return "Dashboard preview";
  if (step.title) return step.title;
  if (!kind) return "Artifact";
  return published ? `Published ${kind}` : `Publishing ${kind}`;
}

export function summarizeArtifact(step: RunStep): ToolCardSummary {
  const result = artifactResult(step);
  const kind = artifactKindForStep(step);
  const failed = step.status === "failed";
  const published = result ? result.published : step.status === "succeeded";
  return {
    title: titleFor(step, kind, published || step.status === "running"),
    stat: artifactName(step),
    ok: !failed && (result ? result.published || kind === "notebook" || kind === "dashboard" : true),
  };
}

function NameLine({ step, running }: { step: RunStep; running: boolean }) {
  const name = artifactName(step);
  const kind = artifactKindForStep(step);
  return (
    <div className="flex items-center gap-2.5 px-3.5 py-2.5">
      {running && <KindIcon Icon={iconForKind("artifact")} running failed={false} />}
      <span className="min-w-0 truncate font-mono text-[11.5px] text-[var(--color-text)]">
        {name ?? "…"}
      </span>
      {kind && (
        <span
          data-testid="chat-publish-kind"
          className="flex-none rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-1.5 py-px text-[10px] text-[var(--color-text-muted)]"
        >
          {kind}
        </span>
      )}
    </div>
  );
}

export function PublishRunning({ step }: ToolCardContext) {
  if (artifactKindForStep(step) === "dashboard") {
    return (
      <div data-testid="chat-publish-card">
        <StepBody step={step} />
      </div>
    );
  }
  return (
    <div data-testid="chat-publish-card">
      <NameLine step={step} running />
    </div>
  );
}

function OpenRow({ step, openArtifact }: { step: RunStep; openArtifact: (id: string) => void }) {
  const ui = useContext(ChatUiContext);
  const name = artifactName(step);
  const file = name
    ? ui?.files.find((entry) => entry.filename === name || entry.path === name)
    : undefined;
  if (!file) return null;
  return (
    <div className="border-t border-[var(--color-border)] px-3.5 py-2">
      <button
        type="button"
        data-testid="chat-publish-open"
        onClick={() => openArtifact(file.id)}
        className="inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-card)] px-2 py-1 text-[11px] text-[var(--color-text)] hover:border-[var(--color-success)]/40 hover:bg-[var(--color-bg-hover)]"
      >
        <ExternalLink className="h-3 w-3 text-[var(--color-text-dim)]" />
        Open
      </button>
    </div>
  );
}

export function PublishExpanded({ step, openArtifact }: ToolCardContext) {
  const result = artifactResult(step);
  const kind = artifactKindForStep(step);
  if (kind === "dashboard") {
    return (
      <div data-testid="chat-publish-card">
        {step.category === "dashboard" ? <StepBody step={step} /> : <DashboardPreviewDetails step={step} />}
      </div>
    );
  }
  const note = result?.nextRequiredAction?.trim();
  const status = result?.status?.trim();
  return (
    <div data-testid="chat-publish-card">
      <NameLine step={step} running={false} />
      {(note || status) && (
        <div className="border-t border-[var(--color-border)] px-3.5 py-2 text-[11px] leading-4 text-[var(--color-text-muted)]">
          {status && (
            <span className="mr-2 font-mono text-[10px] text-[var(--color-text-dim)]">{status}</span>
          )}
          {note && <span data-testid="chat-publish-next">{note}</span>}
        </div>
      )}
      <OpenRow step={step} openArtifact={openArtifact} />
    </div>
  );
}

registerToolCard({
  kind: "artifact",
  Icon: iconForKind("artifact"),
  accent: "artifact",
  summarize: summarizeArtifact,
  Running: PublishRunning,
  Expanded: PublishExpanded,
});
