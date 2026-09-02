"use client";

import {
  FastForward,
  FlaskConical,
  Pause,
  Play,
  RotateCcw,
  Settings2,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChatMessage,
  ChatUiContext,
  type UiMessage,
} from "~/components/chat/standalone-data-chat";
import { ArtifactsPanel } from "~/components/chat/artifacts-panel";
import { hasArtifactsContent } from "~/lib/chat-artifacts";
import { pickDefaultNotebook } from "~/lib/chat-live-notebook";
import {
  FIXTURE_RUN_ID,
  FIXTURE_TOTAL_MS,
  FIXTURE_USER_PROMPT,
  fixtureAssembledText,
  fixtureConversationFiles,
  fixtureConversationNotebooks,
  fixtureFileContent,
  fixtureNowMs,
  fixtureRunStatus,
  fixtureSqlTrace,
  materializeFixtureEvents,
} from "~/lib/chat-test-fixture";
import { NotebookPen } from "lucide-react";
import { useOpenArtifact } from "~/components/chat/use-open-artifact";
import { ChatSettingsPanel } from "~/components/chat/chat-settings-panel";
import { useChatSettingsPanel } from "~/components/chat/use-chat-settings-panel";
import { ConnectorsProvider } from "~/components/connectors/connectors-context";
import { createFixtureConnectorsApi } from "~/lib/mcp-connectors-fixture-client";
import { FIXTURE_ME } from "~/lib/mcp-connectors-fixture";
import { connectorSignInFixtureEvents } from "~/lib/chat-connector-signin-fixture";
import type { StandaloneChatModel } from "~/lib/api";
import {
  FIXTURE_QUERY_RESULT_ID,
  fixtureQueryResultPage,
} from "~/lib/chat-test-fixture-tools";

const SPEEDS = [1, 2, 4] as const;
const TICK_MS = 50;

/**
 * Replays the scripted fixture run through the real chat message components,
 * so the full agent-activity UX can be inspected without a model or gateway.
 * Deterministic entry points for Playwright: /chats/test?at=<ms>&paused=1
 */
export function StandaloneChatTestHarness() {
  const searchParams = useSearchParams();
  const initialAt = Math.min(
    Math.max(Number(searchParams.get("at")) || 0, 0),
    FIXTURE_TOTAL_MS,
  );
  const initiallyPaused = searchParams.get("paused") === "1";
  // Connectors: ?signin=1 adds a connector sign-in failure to the replay;
  // ?settings=1 opens the Chat settings panel; both run on fixture connectors.
  const withSignIn = searchParams.get("signin") === "1";
  const settingsInitiallyOpen = searchParams.get("settings") === "1";
  const connectorsApi = useMemo(
    () => createFixtureConnectorsApi({ latencyMs: 120 }),
    [],
  );
  const [elapsed, setElapsed] = useState(initialAt);
  const [playing, setPlaying] = useState(!initiallyPaused);
  // Flipped by an effect, so it is observable only after React has hydrated
  // and attached event handlers. Click-based Playwright specs gate on this —
  // a click that lands before hydration is silently lost.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [selectedModel, setSelectedModel] =
    useState<StandaloneChatModel>("claude-opus-5");
  const speedRef = useRef(speed);
  speedRef.current = speed;

  useEffect(() => {
    if (!playing) return;
    const interval = window.setInterval(() => {
      setElapsed((value) => {
        const next = value + TICK_MS * speedRef.current;
        if (next >= FIXTURE_TOTAL_MS) {
          window.clearInterval(interval);
          return FIXTURE_TOTAL_MS;
        }
        return next;
      });
    }, TICK_MS);
    return () => window.clearInterval(interval);
  }, [playing]);
  useEffect(() => {
    if (elapsed >= FIXTURE_TOTAL_MS && playing) setPlaying(false);
  }, [elapsed, playing]);

  const events = useMemo(
    () =>
      materializeFixtureEvents(
        elapsed,
        withSignIn ? connectorSignInFixtureEvents : [],
      ),
    [elapsed, withSignIn],
  );

  // Notebook panel: the harness has no gateway, so it simulates the
  // conversation notebook resource from the replayed events. Auto-open
  // mirrors the chat page: once per run when the notebook goes live.
  const conversationNotebooks = useMemo(
    () => fixtureConversationNotebooks(events),
    [events],
  );
  // Auto-open follows the default (analysis) notebook, as on the chat page.
  const defaultNotebook = pickDefaultNotebook(conversationNotebooks);
  const conversationFiles = useMemo(
    () => fixtureConversationFiles(events),
    [events],
  );
  const sqlTraceExecutions = useMemo(() => fixtureSqlTrace(events), [events]);
  const [notebookPanelOpen, setNotebookPanelOpen] = useState(false);
  const settingsPanel = useChatSettingsPanel(
    notebookPanelOpen,
    setNotebookPanelOpen,
  );
  const { openPanel: openSettingsPanel } = settingsPanel;
  useEffect(() => {
    if (settingsInitiallyOpen) openSettingsPanel();
  }, [settingsInitiallyOpen, openSettingsPanel]);
  // Inline artifact cards open the panel focused on their file, as on the
  // real chat page.
  const { openFileRequest, openArtifact } = useOpenArtifact(() =>
    setNotebookPanelOpen(true),
  );
  // File-content stub: the harness has no gateway, so it serves the fixture
  // files' literal contents as object URLs. This keeps the image-card
  // thumbnail path (and any future content-dependent card UI) verifiable
  // at /chats/test.
  const getFileObjectUrl = useCallback(async (fileId: string) => {
    const content = fixtureFileContent(fileId);
    if (!content) throw new Error(`No fixture content for file ${fileId}`);
    return URL.createObjectURL(new Blob([content.body], { type: content.mime }));
  }, []);
  // Full-rows stub for the governed query result: the table card's "Load
  // all rows" pages the same deterministic 1,204 rows the gateway would.
  const getToolResultRows = useCallback(
    async (resultId: string, opts?: { offset?: number; limit?: number }) => {
      if (resultId !== FIXTURE_QUERY_RESULT_ID) {
        throw new Error(`No fixture result for ${resultId}`);
      }
      return fixtureQueryResultPage(opts?.offset, opts?.limit);
    },
    [],
  );
  const notebookPanelAutoOpenedRunRef = useRef<string | null>(null);
  useEffect(() => {
    if (
      defaultNotebook?.status === "live" &&
      notebookPanelAutoOpenedRunRef.current !== FIXTURE_RUN_ID
    ) {
      notebookPanelAutoOpenedRunRef.current = FIXTURE_RUN_ID;
      setNotebookPanelOpen(true);
    }
    if (!defaultNotebook) {
      // Scrubbed back before notebook_started (or restarted): reset so the
      // panel auto-opens again when the notebook (re)starts.
      notebookPanelAutoOpenedRunRef.current = null;
      setNotebookPanelOpen(false);
    }
  }, [defaultNotebook]);
  const status = fixtureRunStatus(elapsed);
  const messages = useMemo<UiMessage[]>(
    () => [
      {
        id: "fixture-user-1",
        role: "user",
        content: FIXTURE_USER_PROMPT,
        sequence: 1,
        created_at: 0,
        metadata: {},
      },
      {
        id: `run-${FIXTURE_RUN_ID}`,
        role: "assistant",
        content: fixtureAssembledText(elapsed),
        sequence: 2,
        created_at: 0,
        metadata: { run_id: FIXTURE_RUN_ID },
        runId: FIXTURE_RUN_ID,
        runStatus: status,
      },
    ],
    [elapsed, status],
  );

  const progress = Math.round((elapsed / FIXTURE_TOTAL_MS) * 100);
  return (
    <div
      className="flex h-full min-h-0 flex-col"
      data-testid="chat-test-harness"
      data-hydrated={hydrated ? "1" : "0"}
    >
      <header className="flex flex-none flex-wrap items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-card)] px-4 py-2.5">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-warning)]/25 bg-[var(--color-warning)]/5 px-2 py-0.5 text-[10px] uppercase tracking-[0.1em] text-[var(--color-warning)]">
          <FlaskConical className="h-3 w-3" />
          Fixture replay
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            data-testid="chat-test-play"
            aria-label={playing ? "Pause replay" : "Play replay"}
            onClick={() => {
              if (elapsed >= FIXTURE_TOTAL_MS) setElapsed(0);
              setPlaying((value) => !value);
            }}
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-text)] hover:border-[var(--color-border-hover)]"
          >
            {playing ? (
              <Pause className="h-3.5 w-3.5" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            data-testid="chat-test-restart"
            aria-label="Restart replay"
            onClick={() => {
              setElapsed(0);
              setPlaying(true);
            }}
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            data-testid="chat-test-skip"
            aria-label="Skip to end"
            onClick={() => {
              setElapsed(FIXTURE_TOTAL_MS);
              setPlaying(false);
            }}
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-text-muted)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
          >
            <FastForward className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="flex items-center gap-1">
          {SPEEDS.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setSpeed(value)}
              className={`rounded-md px-2 py-1 text-[11px] tabular-nums ${
                speed === value
                  ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
                  : "text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
              }`}
            >
              {value}×
            </button>
          ))}
        </div>
        <input
          type="range"
          aria-label="Replay position"
          data-testid="chat-test-scrub"
          min={0}
          max={FIXTURE_TOTAL_MS}
          step={100}
          value={elapsed}
          onChange={(event) => {
            setPlaying(false);
            setElapsed(Number(event.target.value));
          }}
          className="h-1 min-w-32 flex-1 accent-[var(--color-success)]"
        />
        <span className="w-20 text-right text-[11px] tabular-nums text-[var(--color-text-dim)]">
          {(elapsed / 1000).toFixed(1)}s · {progress}%
        </span>
        <button
          type="button"
          aria-label="Chat settings"
          aria-expanded={settingsPanel.open}
          data-testid="chat-settings-gear"
          onClick={settingsPanel.toggle}
          className={`flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] ${
            settingsPanel.open
              ? "bg-[var(--color-bg-hover)] text-[var(--color-text)]"
              : "bg-[var(--color-bg-input)] text-[var(--color-text-muted)]"
          }`}
        >
          <Settings2 className="h-3.5 w-3.5" />
        </button>
      </header>
      <ConnectorsProvider api={connectorsApi} fixture currentUserId={FIXTURE_ME}>
      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        <div
          className="min-h-0 min-w-0 flex-1 overflow-y-auto"
          data-testid="chat-test-viewport"
        >
          <ChatUiContext.Provider
            value={{
              events,
              conversationId: "conversation-fixture-1",
              files: conversationFiles,
              runningRunId:
                status === "queued" || status === "running"
                  ? FIXTURE_RUN_ID
                  : null,
              openArtifact,
              getFileObjectUrl,
              getToolResultRows,
              // Frozen replay clock, so relative timestamps are honest on
              // every frame instead of measuring from the real wall clock.
              nowMs: fixtureNowMs(elapsed),
              openChatSettings: settingsPanel.openPanel,
              onStop: async () => undefined,
              onRetry: async () => undefined,
              onOpenDashboardPreview: () => undefined,
            }}
          >
            <div className="py-6" data-testid="standalone-chat-messages">
              {messages.map((message) => (
                <ChatMessage key={message.id} message={message} />
              ))}
            </div>
          </ChatUiContext.Provider>
        </div>
        {hasArtifactsContent(
          conversationNotebooks,
          conversationFiles,
          sqlTraceExecutions,
        ) &&
          !notebookPanelOpen &&
          !settingsPanel.open && (
          <button
            type="button"
            aria-label="Open the artifacts panel"
            title="Open the artifacts panel"
            data-testid="live-notebook-toggle"
            onClick={() => setNotebookPanelOpen(true)}
            className="absolute right-4 top-4 z-20 flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-muted)] shadow-lg shadow-black/20 hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
          >
            <NotebookPen className="h-4 w-4" />
          </button>
        )}
        {settingsPanel.open && (
          <ChatSettingsPanel
            onClose={settingsPanel.closePanel}
            connectorsEnabled
            model={{
              value: selectedModel,
              options: [
                { id: "claude-opus-4-6", label: "Opus 4.6" },
                { id: "claude-sonnet-4-6", label: "Sonnet 4.6" },
                { id: "claude-opus-5", label: "Opus 5" },
                { id: "claude-fable-5-1", label: "Fable 5.1" },
              ],
              disabled: false,
              onChange: setSelectedModel,
            }}
            manageHref="/settings/connectors?fixture=1"
          />
        )}
        {notebookPanelOpen && !settingsPanel.open && (
          <ArtifactsPanel
            conversationId="conversation-fixture-1"
            notebooks={conversationNotebooks}
            files={conversationFiles}
            executions={sqlTraceExecutions}
            openFileRequest={openFileRequest}
            onClose={() => setNotebookPanelOpen(false)}
            liveViewOverride={
              <div
                data-testid="chat-notebook-stub"
                className="flex h-full items-center justify-center text-xs text-[var(--color-text-dim)]"
              >
                Live notebook view stub
              </div>
            }
            fileViewOverride={
              <div
                data-testid="chat-file-stub"
                className="flex h-full items-center justify-center text-xs text-[var(--color-text-dim)]"
              >
                File viewer stub
              </div>
            }
          />
        )}
      </div>
      </ConnectorsProvider>
    </div>
  );
}
