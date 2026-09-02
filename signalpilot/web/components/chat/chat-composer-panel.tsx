"use client";

// Composer block for the standalone data chat: input, project picker, and
// the gear that opens the right-side Chat settings panel.

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
  onOpenSettings,
  settingsOpen,
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
  /** Present whenever the chat has settings to show (connectors, budgets). */
  onOpenSettings?: () => void;
  settingsOpen?: boolean;
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
      onOpenSettings={onOpenSettings}
      settingsOpen={settingsOpen}
    />
  );
}
