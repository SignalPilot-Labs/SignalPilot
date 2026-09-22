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
import { PLAN_FILE_PATH } from "~/lib/chat-run-steps";
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
import { DefaultProjectControl } from "~/components/chat/default-project-control";

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
  defaultProjectId = null,
  onSetDefaultProject,
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
  /** The org-wide default project; the setter is admin-only. */
  defaultProjectId?: string | null;
  onSetDefaultProject?: (projectId: string) => void;
  /** Present whenever the chat has settings to show (connectors, budgets). */
  onOpenSettings?: () => void;
  settingsOpen?: boolean;
}) {
  const selectedProject =
    bootstrap.projects.find((p) => p.id === selectedProjectId) ?? null;
  // The run's live state for the Stop ring and hint. The panel renders
  // inside the chat UI provider on the live page; without one (harness,
  // tests) there are no events and the state stays idle.
  const ui = useContext(ChatUiContext);
  const events = ui?.events ?? EMPTY_EVENTS;
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
  // A plan kept in artifacts/plan.md opens in the artifacts panel.
  const planFileId = ui?.files.find((file) => file.path === PLAN_FILE_PATH)?.id;
  const openArtifact = ui?.openArtifact;
  const onOpenPlan = useMemo(
    () =>
      planFileId && openArtifact ? () => openArtifact(planFileId) : undefined,
    [planFileId, openArtifact],
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
          <div className="flex min-w-0 items-center gap-2">
            <ProjectPicker
              projects={bootstrap.projects}
              selectedId={selectedProjectId}
              onSelect={onSelectProject}
            />
            {onSetDefaultProject && (
              <DefaultProjectControl
                selectedProjectId={selectedProjectId}
                defaultProjectId={defaultProjectId}
                onSetDefault={onSetDefaultProject}
              />
            )}
          </div>
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
      onOpenPlan={onOpenPlan}
    />
  );
}
