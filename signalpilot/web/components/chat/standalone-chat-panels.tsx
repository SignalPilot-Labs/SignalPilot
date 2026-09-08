"use client";

// The right-hand slot of the standalone data chat: floating toggles over the
// transcript and the one panel showing at a time (artifacts, chat settings,
// or the dashboard preview). The container owns the open/close state; this
// module only renders it.

import { History, LayoutDashboard, Loader2, NotebookPen, Share2 } from "lucide-react";
import type {
  ConversationFileInfo,
  ConversationNotebook,
  SqlTraceExecution,
} from "~/lib/api";
import { ArtifactsPanel } from "~/components/chat/artifacts-panel";
import type { ArtifactOpenRequest } from "~/components/chat/use-open-artifact";
import { ChatDashboardPanel } from "~/components/chat/chat-dashboard-panel";
import {
  ChatSettingsPanel,
  type ChatBudgetSettings,
  type ChatModelSettings,
} from "~/components/chat/chat-settings-panel";

const TOGGLE_CLASS =
  "flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)] shadow-lg shadow-black/20 hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]";

export function ChatPanelToggles({
  artifactsAvailable,
  artifactsLoading,
  artifactsOpen,
  onOpenArtifacts,
  dashboardSessionId,
  dashboardOpen,
  onOpenDashboard,
  onShare,
  onReplay,
}: {
  /** Owner pages with team sharing: the share-link action. */
  onShare?: () => void;
  /** Offered only when the conversation has something to replay. */
  onReplay?: () => void;
  artifactsAvailable: boolean;
  artifactsLoading: boolean;
  artifactsOpen: boolean;
  onOpenArtifacts: () => void;
  /** The newest dashboard preview session, when the run produced one. */
  dashboardSessionId: string | null;
  dashboardOpen: boolean;
  onOpenDashboard: (sessionId: string) => void;
}) {
  // One floating row, outermost action last, so absent toggles leave no gap.
  return (
    <div className="absolute right-4 top-4 z-20 flex items-center gap-3">
      {onReplay && (
        <button
          type="button"
          aria-label="Replay chat"
          title="Replay this conversation as it happened"
          data-testid="chat-replay-button"
          onClick={onReplay}
          className={TOGGLE_CLASS}
        >
          <History className="h-4 w-4" />
        </button>
      )}
      {dashboardSessionId && !dashboardOpen && (
        <button
          type="button"
          aria-label="Open the dashboard preview"
          title="Open the dashboard preview"
          data-testid="chat-dashboard-toggle"
          onClick={() => onOpenDashboard(dashboardSessionId)}
          className={TOGGLE_CLASS}
        >
          <LayoutDashboard className="h-4 w-4" />
        </button>
      )}
      {(artifactsLoading || artifactsAvailable) && !artifactsOpen && (
        <button
          type="button"
          aria-label="Open the artifacts panel"
          title="Open the artifacts panel"
          data-testid="live-notebook-toggle"
          onClick={onOpenArtifacts}
          className={TOGGLE_CLASS}
        >
          {artifactsLoading ? (
            <Loader2
              data-testid="artifacts-toggle-loading"
              className="h-4 w-4 animate-spin"
            />
          ) : (
            <NotebookPen className="h-4 w-4" />
          )}
        </button>
      )}
      {onShare && (
        <button
          type="button"
          aria-label="Share conversation"
          title="Create a new authenticated team link and revoke any previous link"
          onClick={onShare}
          className={TOGGLE_CLASS}
        >
          <Share2 className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

export function ChatRightPanels({
  conversationId,
  artifacts,
  settings,
  dashboard,
}: {
  conversationId: string;
  artifacts: {
    open: boolean;
    notebooks: ConversationNotebook[];
    files: ConversationFileInfo[];
    executions: SqlTraceExecution[];
    loading: boolean;
    openFileRequest: ArtifactOpenRequest | null;
    onClose: () => void;
  };
  settings: {
    open: boolean;
    connectorsEnabled: boolean;
    model: ChatModelSettings;
    budgets: ChatBudgetSettings | null;
    onClose: () => void;
  };
  dashboard: {
    sessionId: string | null;
    updateLabel: string | null;
    updateRevision: number;
    queriesEnabled: boolean;
    onClose: () => void;
  };
}) {
  // Settings wins the slot; the hooks keep at most one sibling open.
  if (settings.open) {
    return (
      <ChatSettingsPanel
        onClose={settings.onClose}
        connectorsEnabled={settings.connectorsEnabled}
        model={settings.model}
        budgets={settings.budgets}
      />
    );
  }
  if (dashboard.sessionId) {
    return (
      <ChatDashboardPanel
        sessionId={dashboard.sessionId}
        updateLabel={dashboard.updateLabel}
        updateRevision={dashboard.updateRevision}
        queriesEnabled={dashboard.queriesEnabled}
        onClose={dashboard.onClose}
      />
    );
  }
  if (artifacts.open) {
    return (
      <ArtifactsPanel
        conversationId={conversationId}
        notebooks={artifacts.notebooks}
        files={artifacts.files}
        executions={artifacts.executions}
        loading={artifacts.loading}
        openFileRequest={artifacts.openFileRequest}
        onClose={artifacts.onClose}
      />
    );
  }
  return null;
}
