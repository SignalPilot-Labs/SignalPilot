"use client";

// Composer block for the standalone data chat: input, project picker,
// and optional budget settings.

import type { Dispatch, SetStateAction } from "react";
import type {
  StandaloneChatBootstrap,
  StandaloneChatRun,
} from "~/lib/api";
import { StandaloneChatComposer } from "~/components/chat/standalone-chat-composer";
import {
  ProjectChip,
  ProjectPicker,
} from "~/components/chat/project-picker";

export function ChatComposerPanel({
  draft,
  setDraft,
  submitText,
  submitDisabled,
  disabledReason,
  runIsStreaming,
  currentRun,
  onStop,
  mentionOptions,
  conversationId,
  bootstrap,
  selectedProjectId,
  onSelectProject,
  perQueryBudgetUsd,
  setPerQueryBudgetUsd,
  chatBudgetUsd,
  setChatBudgetUsd,
}: {
  draft: string;
  setDraft: Dispatch<SetStateAction<string>>;
  submitText: (text: string) => Promise<void>;
  submitDisabled: boolean;
  disabledReason: string | undefined;
  runIsStreaming: boolean;
  currentRun: StandaloneChatRun | null;
  onStop: (runId: string) => Promise<void>;
  mentionOptions: string[];
  conversationId?: string;
  bootstrap: StandaloneChatBootstrap;
  selectedProjectId: string | null;
  onSelectProject: (projectId: string) => void;
  perQueryBudgetUsd: number;
  setPerQueryBudgetUsd: Dispatch<SetStateAction<number>>;
  chatBudgetUsd: number;
  setChatBudgetUsd: Dispatch<SetStateAction<number>>;
}) {
  const selectedProject =
    bootstrap.projects.find((p) => p.id === selectedProjectId) ?? null;
  return (
    <StandaloneChatComposer
      value={draft}
      onValueChange={setDraft}
      onSubmit={(text) => void submitText(text)}
      submitDisabled={submitDisabled}
      disabledReason={disabledReason}
      running={runIsStreaming}
      onStop={currentRun ? () => void onStop(currentRun.id) : undefined}
      mentionOptions={mentionOptions}
      placeholder={
        currentRun?.status === "waiting_for_user"
          ? "Answer the clarification…"
          : currentRun?.status === "running"
            ? "Add an instruction for the agent's next turn…"
          : currentRun?.status === "waiting_for_query_approval"
            ? "Approve or decline the proposed query above…"
            : "Ask anything about this project…"
      }
      projectPicker={
        !conversationId ? (
          <ProjectPicker
            projects={bootstrap.projects}
            selectedId={selectedProjectId}
            onSelect={onSelectProject}
          />
        ) : (
          <ProjectChip project={selectedProject} />
        )
      }
      settings={
        !conversationId && bootstrap.enterprise_features.query_approval ? (
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-[10px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]">
                Per-query budget (USD)
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={perQueryBudgetUsd}
                onChange={(event) =>
                  setPerQueryBudgetUsd(Math.max(0, Number(event.target.value)))
                }
                aria-label="Per-query budget in USD"
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1.5 text-xs text-[var(--color-text)]"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[10px] uppercase tracking-[0.08em] text-[var(--color-text-dim)]">
                Chat budget (USD)
              </span>
              <input
                type="number"
                min={perQueryBudgetUsd}
                step="0.01"
                value={chatBudgetUsd}
                onChange={(event) =>
                  setChatBudgetUsd(
                    Math.max(perQueryBudgetUsd, Number(event.target.value)),
                  )
                }
                aria-label="Chat budget in USD"
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-2 py-1.5 text-xs text-[var(--color-text)]"
              />
            </label>
          </div>
        ) : undefined
      }
    />
  );
}
