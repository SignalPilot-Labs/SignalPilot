"use client";

// Composer block for the standalone data chat: input, project picker, and
// the gear that opens the right-side Chat settings panel.

import {
  useContext,
  useMemo,
  type Dispatch,
  type SetStateAction,
} from "react";
import { selectComposerPlan } from "~/lib/chat-composer-plan";
import type {
  StandaloneChatBootstrap,
  StandaloneChatEvent,
  StandaloneChatRun,
} from "~/lib/api";
import { StandaloneChatComposer } from "~/components/chat/standalone-chat-composer";
import { ChatUiContext } from "~/components/chat/chat-ui-context";
import { useRunLiveState } from "~/components/chat/use-run-live-state";
import {
  ProjectChip,
  ProjectPicker,
} from "~/components/chat/project-picker";

const EMPTY_EVENTS: StandaloneChatEvent[] = [];

export function ChatComposerPanel({
  draft,
  setDraft,
  submitText,
  submitDisabled,
  disabledReason,
  runIsStreaming,
  currentRun,
  onStop,
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
  // The run's live state for the Stop ring and hint. The panel renders
  // inside the chat UI provider on the live page; without one (harness,
  // tests) there are no events and the state stays idle.
  const events = useContext(ChatUiContext)?.events ?? EMPTY_EVENTS;
  const live = useRunLiveState(
    events,
    currentRun?.id,
    currentRun?.status ?? "completed",
  );
  // The current run's plan, docked above the input. Derived from the same
  // events the transcript folds, so a refresh rehydrates it for free.
  const composerPlan = useMemo(
    () => selectComposerPlan(events, currentRun),
    [events, currentRun],
  );
  return (
    <StandaloneChatComposer
      value={draft}
      onValueChange={setDraft}
      onSubmit={(text) => void submitText(text)}
      submitDisabled={submitDisabled}
      disabledReason={disabledReason}
      running={runIsStreaming}
      onStop={currentRun ? () => void onStop(currentRun.id) : undefined}
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
      liveState={live.state}
      liveLabel={live.label}
      plan={composerPlan?.plan ?? null}
      planRunning={composerPlan?.running ?? false}
    />
  );
}
