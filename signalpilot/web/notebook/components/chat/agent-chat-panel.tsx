import {
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  KeyRoundIcon,
  Loader2,
  PenLineIcon,
  PlayIcon,
  PlusIcon,
  SearchIcon,
  SendIcon,
  SparklesIcon,
  SquareIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react";
import { MarkdownRenderer } from "@/components/markdown/markdown-renderer";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import useEvent from "react-use-event-hook";
import { useAtomValue } from "jotai";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { useActiveFile } from "@/core/active-file";
import { useRuntimeManager } from "@/core/runtime/config";
import { filenameAtom } from "@/core/saving/file-state";
import {
  isNotionTrailParams,
  notionRequestIdFromSessionId,
} from "@/core/notion/trail";
import { cn } from "@/utils/cn";
import {
  useAgentChat,
  type AgentMessage,
  type AgentToolCall,
} from "@/hooks/useAgentChat";
import {
  parseFinalJsonSummary,
  type FinalJsonSummary,
} from "./final-json";


/* ── API Key Setup ── */
const ApiKeySetup: React.FC<{ onConfigured: () => void }> = ({ onConfigured }) => {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const runtimeManager = useRuntimeManager();

  const handleSave = async () => {
    if (!apiKey.trim()) {return;}
    setSaving(true);
    setError("");
    try {
      const resp = await fetch(
        runtimeManager.getAgentURL("save-api-key").toString(),
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await runtimeManager.headers()) },
          body: JSON.stringify({ api_key: apiKey.trim() }),
        },
      );
      const data = await resp.json() as { success?: boolean; error?: string };
      if (data.success) {
        onConfigured();
      } else {
        setError(data.error || "Failed to save");
      }
    } catch (e) {
      setError(String(e));
    }
    setSaving(false);
  };

  return (
    <div className="flex flex-col items-center justify-center h-full p-6 text-center gap-4">
      <KeyRoundIcon className="h-10 w-10 text-muted-foreground opacity-30" />
      <div>
        <h3 className="text-sm font-semibold text-foreground mb-1">Set up AI Agent</h3>
        <p className="text-xs text-muted-foreground">
          Enter your Anthropic API key to enable the AI agent.
        </p>
      </div>
      <div className="w-full max-w-xs space-y-2">
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") {handleSave();} }}
          placeholder="sk-ant-..."
          className={cn(
            "w-full rounded-md border border-border bg-background px-3 py-2 text-xs font-mono",
            "placeholder:text-muted-foreground/50",
            "focus:outline-none focus:ring-1 focus:ring-primary/40",
          )}
        />
        {error && <p className="text-[11px] text-red-500">{error}</p>}
        <Button
          variant="default"
          size="sm"
          className="w-full"
          onClick={handleSave}
          disabled={!apiKey.trim() || saving}
        >
          {saving ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
          Save API Key
        </Button>
      </div>
      <p className="text-[10px] text-muted-foreground max-w-xs">
        Your key is stored securely on the server. Get one at{" "}
        <a href="https://console.anthropic.com" target="_blank" rel="noopener noreferrer"
          className="text-primary hover:underline">console.anthropic.com</a>
      </p>
    </div>
  );
};


/* ── Constants ── */
const SCROLL_THRESHOLD = 20;
const MAX_TEXTAREA_ROWS = 8;
const TEXTAREA_LINE_HEIGHT = 22;
const TEXTAREA_PADDING = 20;
const NOTION_THREAD_EVENT = "sp:notion-thread-resolved";
const NOTION_THREAD_STORAGE_PREFIX = "sp:notion-thread:";

type NotionThreadWindow = Window & {
  __signalPilotNotionThreadId?: string;
  __signalPilotNotionThreadByFile?: Record<string, string>;
};

function normalizeNotionTrailFile(file?: string | null) {
  return file?.replace(/^\/+/, "") ?? "";
}

function getRememberedNotionThreadId(file?: string | null) {
  if (typeof window === "undefined") {return null;}

  const trailFile = normalizeNotionTrailFile(file);
  const win = window as NotionThreadWindow;
  const rememberedByFile = trailFile
    ? win.__signalPilotNotionThreadByFile?.[trailFile]
    : null;
  const rememberedGlobal = win.__signalPilotNotionThreadId ?? null;
  const rememberedLocal = trailFile
    ? window.localStorage.getItem(`${NOTION_THREAD_STORAGE_PREFIX}${trailFile}`)
    : null;

  const threadId = rememberedByFile || rememberedLocal || rememberedGlobal;
  return notionRequestIdFromSessionId(threadId) ? threadId : null;
}

/* ── Main Panel ── */
const AgentChatPanel: React.FC = () => {
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(true);
  const runtimeManager = useRuntimeManager();

  useEffect(() => {
    const check = async () => {
      try {
        const headers = await runtimeManager.headers();
        fetch(runtimeManager.getAgentURL("auth-status").toString(), { headers })
          .then((r): Promise<{ configured?: boolean }> => r.ok ? r.json() : Promise.resolve({ configured: true }))
          .then((data) => setAiConfigured(data.configured ?? true))
          .catch(() => setAiConfigured(true));
      } catch {
        setAiConfigured(true);
      }
    };
    void check();
  }, [runtimeManager]);

  if (aiConfigured === null) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin mr-2" />
        Checking AI configuration...
      </div>
    );
  }

  if (!aiConfigured) {
    return <ApiKeySetup onConfigured={() => setAiConfigured(true)} />;
  }

  return <AgentChatPanelInner />;
};

const AgentChatPanelInner: React.FC = () => {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const runtimeManager = useRuntimeManager();
  const activeFile = useActiveFile();
  const notebookFilename = useAtomValue(filenameAtom);
  const urlParams =
    typeof window === "undefined"
      ? null
      : new URLSearchParams(window.location.search);
  const urlSessionId =
    urlParams?.get("session_id") ?? null;
  const urlFile = urlParams?.get("file") ?? null;
  const urlNotionThreadId = notionRequestIdFromSessionId(urlSessionId)
    ? urlSessionId
    : null;
  const notionTrailFile = urlFile;
  const [rememberedNotionThreadId, setRememberedNotionThreadId] = useState(
    () => getRememberedNotionThreadId(notionTrailFile),
  );
  const explicitNotionThreadId =
    urlNotionThreadId ?? rememberedNotionThreadId;
  const includeNotionConversations =
    Boolean(explicitNotionThreadId) ||
    isNotionTrailParams({ file: notionTrailFile, sessionId: urlSessionId });
  const notionAutoLoadAttempts = useRef<Record<string, number>>({});

  useEffect(() => {
    const syncRememberedThread = () => {
      setRememberedNotionThreadId(getRememberedNotionThreadId(notionTrailFile));
    };

    syncRememberedThread();
    window.addEventListener(NOTION_THREAD_EVENT, syncRememberedThread);
    window.addEventListener("storage", syncRememberedThread);
    return () => {
      window.removeEventListener(NOTION_THREAD_EVENT, syncRememberedThread);
      window.removeEventListener("storage", syncRememberedThread);
    };
  }, [notionTrailFile]);

  const getActiveFile = useCallback(() => {
    return activeFile?.path || notebookFilename || null;
  }, [activeFile, notebookFilename]);

  const {
    messages,
    sendMessage,
    stopAgent,
    isStreaming,
    isLoadingSessions,
    isLoadingMessages,
    error,
    clearMessages,
    chatSessions,
    activeSessionId,
    loadSession,
    deleteSession,
    renameSession,
  } = useAgentChat({
    baseUrl: runtimeManager.getAgentBaseURL(),
    headers: () => runtimeManager.headers(),
    getActiveFile,
    includeNotionConversations,
    initialSessionId: explicitNotionThreadId,
  });

  const matchedNotionThreadId = useMemo(() => {
    if (explicitNotionThreadId || !notionTrailFile) {return null;}

    const trailFile = normalizeNotionTrailFile(notionTrailFile);
    const session = chatSessions.find((chatSession) => {
      const notebookPath = chatSession.notebookPath?.replace(/^\/+/, "");
      if (!notebookPath) {return false;}
      return (
        (chatSession.source === "notion" || chatSession.source === "slack") &&
        (notebookPath === trailFile ||
          notebookPath.endsWith(`/${trailFile}`) ||
          trailFile.endsWith(notebookPath))
      );
    });
    const sessionId = session?.id;
    return notionRequestIdFromSessionId(sessionId) ? sessionId : null;
  }, [chatSessions, explicitNotionThreadId, notionTrailFile]);

  const notionThreadId = explicitNotionThreadId ?? matchedNotionThreadId;

  useEffect(() => {
    const trailSessionId = notionRequestIdFromSessionId(notionThreadId)
      ? notionThreadId
      : null;
    if (
      urlSessionId ||
      !trailSessionId ||
      !isNotionTrailParams({ file: notionTrailFile, sessionId: trailSessionId }) ||
      typeof window === "undefined"
    ) {
      return;
    }

    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("session_id", trailSessionId);
    window.history.replaceState(null, "", nextUrl.toString());
  }, [notionThreadId, notionTrailFile, urlSessionId]);

  useEffect(() => {
    const hasLoadedThread =
      activeSessionId === notionThreadId && messages.length > 0;
    const waitingForMatchedThread =
      !explicitNotionThreadId && isLoadingSessions;
    if (
      !notionThreadId ||
      waitingForMatchedThread ||
      isLoadingMessages ||
      hasLoadedThread
    ) {
      return;
    }

    const attempts = notionAutoLoadAttempts.current[notionThreadId] ?? 0;
    if (attempts >= 4) {return;}

    notionAutoLoadAttempts.current[notionThreadId] = attempts + 1;
    const timeout = window.setTimeout(
      () => loadSession(notionThreadId),
      attempts === 0 ? 0 : attempts * 750,
    );
    return () => window.clearTimeout(timeout);
  }, [
    activeSessionId,
    explicitNotionThreadId,
    notionThreadId,
    isLoadingSessions,
    isLoadingMessages,
    messages.length,
    loadSession,
  ]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, autoScroll]);

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) {return;}
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const isAtBottom =
      scrollHeight - scrollTop - clientHeight < SCROLL_THRESHOLD;
    setAutoScroll(isAtBottom);
  }, []);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) {return;}
    el.style.height = "auto";
    const maxH = TEXTAREA_LINE_HEIGHT * MAX_TEXTAREA_ROWS + TEXTAREA_PADDING;
    const clamped = Math.min(el.scrollHeight, maxH);
    el.style.height = `${clamped}px`;
    el.style.overflowY = el.scrollHeight > maxH ? "auto" : "hidden";
  }, [input]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleSubmit = useEvent(() => {
    const text = input.trim();
    if (!text || isStreaming) {return;}
    sendMessage(text);
    setInput("");
    setAutoScroll(true);
  });

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex flex-col h-[calc(100%-53px)]">
      {/* Header */}
      <div className="flex border-b px-3 py-2 justify-between shrink-0 items-center">
        <div className="flex items-center gap-2">
          <Tooltip content="New chat">
            <Button variant="text" size="icon" onClick={clearMessages}>
              <PlusIcon className="h-4 w-4" />
            </Button>
          </Tooltip>
          <AgentChatHistorySidebar
            sessions={chatSessions}
            isLoading={isLoadingSessions}
            onLoadSession={loadSession}
            onDeleteSession={deleteSession}
            onRenameSession={renameSession}
          />
          <span className="text-xs text-muted-foreground uppercase tracking-wider font-semibold">
            SignalPilot Agent
          </span>
        </div>
        {isStreaming && (
          <div className="flex items-center gap-1.5 text-xs text-green-500 font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            streaming
          </div>
        )}
      </div>

      {/* Event Feed */}
      <div
        className="flex-1 overflow-y-auto px-3 py-3 space-y-2 min-h-0"
        ref={scrollRef}
        onScroll={handleScroll}
      >
        {isLoadingMessages && (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground text-sm p-6 text-center gap-2 h-full">
            <Loader2 className="h-6 w-6 animate-spin opacity-50" />
            <p className="text-xs">Loading conversation...</p>
          </div>
        )}

        {!isLoadingMessages && messages.length === 0 && !isStreaming && (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground text-sm p-6 text-center gap-2 h-full">
            <SparklesIcon className="h-8 w-8 opacity-30" />
            <p>Ask anything about your notebook or data.</p>
            <p className="text-xs opacity-60">
              The agent can read cells, query databases, and edit your notebook.
            </p>
          </div>
        )}

        {!isLoadingMessages && messages.map((msg, idx) => (
          <EventCard
            key={msg.id}
            message={msg}
            isLast={idx === messages.length - 1}
            isStreaming={isStreaming}
          />
        ))}

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive font-mono whitespace-pre-wrap break-words max-h-[200px] overflow-y-auto">
            {error}
          </div>
        )}
      </div>

      {/* Stop button */}
      {isStreaming && (
        <div className="flex justify-center border-t py-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive text-xs gap-1"
            onClick={stopAgent}
          >
            <SquareIcon className="h-3 w-3" />
            Stop
          </Button>
        </div>
      )}

      {/* Input Area */}
      <div className="border-t p-2 shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isStreaming ? "Agent is working..." : "Message the agent..."
            }
            rows={2}
            disabled={isStreaming}
            className={cn(
              "w-full rounded-lg border px-3 py-2.5 text-sm leading-[22px]",
              "bg-background text-foreground",
              "placeholder:text-muted-foreground/60",
              "resize-none",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 focus-visible:border-primary/40",
              "transition-all duration-150",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
            style={{ minHeight: "60px" }}
          />
          <Button
            size="icon"
            variant="default"
            onClick={handleSubmit}
            disabled={!input.trim() || isStreaming}
            className="h-[44px] w-[44px] shrink-0 rounded-lg"
          >
            {isStreaming ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <SendIcon className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
};

/* ── Event Card Router ── */
const EventCard: React.FC<{
  message: AgentMessage;
  isLast: boolean;
  isStreaming: boolean;
}> = ({ message, isLast, isStreaming }) => {
  if (message.role === "user") {
    return <UserBubble content={message.content} />;
  }
  const isEmpty =
    !message.content &&
    !message.thinking &&
    (!message.toolCalls || message.toolCalls.length === 0);
  if (isEmpty && !(isLast && isStreaming)) {return null;}
  return (
    <AssistantCard
      message={message}
      isLast={isLast}
      isStreaming={isStreaming}
    />
  );
};

/* ── User Bubble ── */
const UserBubble: React.FC<{ content: string }> = ({ content }) => (
  <div className="flex justify-end px-1 py-0.5">
    <div className="max-w-[80%] min-w-0 rounded-2xl rounded-tr-sm bg-primary/10 border border-primary/20 px-4 py-2.5 overflow-hidden">
      <div className="text-xs font-semibold uppercase tracking-wider text-primary/70 mb-1">
        You
      </div>
      <div className="text-sm text-foreground break-words leading-relaxed max-h-[300px] overflow-y-auto">
        <MarkdownRenderer content={content} />
      </div>
    </div>
  </div>
);

/* ── Assistant Card ── */
const AssistantCard: React.FC<{
  message: AgentMessage;
  isLast: boolean;
  isStreaming: boolean;
}> = ({ message, isLast, isStreaming }) => {
  const [showThinking, setShowThinking] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const finalJson = useMemo(
    () => parseFinalJsonSummary(message.content),
    [message.content],
  );
  const showCursor = isLast && isStreaming && !message.toolCalls?.length;
  const toolCount = message.toolCalls?.length ?? 0;

  return (
    <div
      className={cn(
        "rounded-lg border-l-2 border border-border/50 overflow-hidden transition-all duration-150",
        "bg-card/50 border-l-green-500/60",
        "hover:border-l-[3px]",
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="flex items-center justify-center h-6 w-6 rounded-md bg-green-500/10 shrink-0">
          <SparklesIcon className="h-3 w-3 text-green-500" />
        </div>
        <span className="text-xs font-semibold text-green-500">
          SignalPilot
        </span>
        {message.thinking && (
          <button
            onClick={() => setShowThinking(!showThinking)}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
          >
            <svg
              width="10"
              height="10"
              viewBox="0 0 10 10"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <circle cx="5" cy="5" r="3.5" />
              <circle cx="5" cy="5" r="1" />
            </svg>
            {showThinking ? "hide reasoning" : "show reasoning"}
          </button>
        )}
      </div>

      {/* Thinking */}
      {showThinking && message.thinking && (
        <div className="mx-3 mb-2 px-3 py-2 bg-muted/30 rounded border border-border/30 overflow-hidden">
          <div className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-1">
            Reasoning
          </div>
          <div className="text-xs text-muted-foreground italic leading-relaxed break-words max-h-[200px] overflow-y-auto">
            <MarkdownRenderer content={message.thinking} />
          </div>
        </div>
      )}

      {/* Text Content */}
      {message.content && (
        <div className="px-3 pb-3 text-sm text-foreground/90 break-words leading-relaxed">
          {finalJson ? (
            <FinalJsonCard result={finalJson} />
          ) : (
            <MarkdownRenderer content={message.content} />
          )}
          {showCursor && (
            <span
              className="inline-block w-[5px] h-[14px] ml-0.5 rounded-[1px] bg-green-500/30"
              style={{ animation: "blink 1s step-end infinite" }}
            />
          )}
        </div>
      )}

      {/* Tool Calls */}
      {toolCount > 0 && (
        <div className="mx-3 mb-2">
          <button
            onClick={() => setShowTools(!showTools)}
            className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {showTools ? "hide" : "show"} technical activity ({toolCount})
          </button>
          {showTools && (
            <div className="mt-1.5 space-y-1.5">
              {message.toolCalls?.map((tc) => (
                <ToolCallCard key={tc.id} toolCall={tc} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Loading / thinking state */}
      {isLast && isStreaming && !message.content && !message.toolCalls?.length && (
        <div className="flex items-center gap-2 px-3 pb-3">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-green-500/60" />
          <span className="text-[11px] text-muted-foreground animate-pulse">
            Thinking...
          </span>
        </div>
      )}

      {/* Active tool indicator */}
      {isLast && isStreaming && message.toolCalls && message.toolCalls.some((tc) => !tc.result) && (
        <div className="flex items-center gap-2 px-3 pb-2 border-t border-border/30 pt-2 mt-1">
          <Loader2 className="h-3 w-3 animate-spin text-yellow-500" />
          <span className="text-[10px] text-yellow-500 font-medium">
            Running {message.toolCalls.filter((tc) => !tc.result).map((tc) =>
              tc.name.replace(/^mcp__signalpilot__/, "")
            ).join(", ")}...
          </span>
        </div>
      )}
    </div>
  );
};

/* ── Final JSON Compact View ── */
const FinalJsonCard: React.FC<{ result: FinalJsonSummary }> = ({ result }) => {
  const [showRaw, setShowRaw] = useState(false);
  const confidence =
    result.confidenceScore === null
      ? "not provided"
      : result.confidenceScore.toFixed(2);
  const chartCount = result.notionCharts.length;
  const caveatCount = result.gotchas.length;
  const commentPreview = result.notionComment.trim();

  return (
    <div className="rounded-md border border-green-500/20 bg-green-500/[0.03] overflow-hidden">
      <div className="px-3 py-2 border-b border-green-500/10">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider font-semibold text-green-500">
            Final Notion JSON
          </span>
          <span className="text-[10px] text-muted-foreground">
            confidence {confidence}
          </span>
          <button
            onClick={() => setShowRaw((value) => !value)}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
          >
            {showRaw ? (
              <ChevronDownIcon className="h-3 w-3" />
            ) : (
              <ChevronRightIcon className="h-3 w-3" />
            )}
            {showRaw ? "hide JSON" : "show JSON"}
          </button>
        </div>
        {result.summary && (
          <div className="mt-1 text-sm text-foreground/90">
            {result.summary}
          </div>
        )}
      </div>
      <div className="px-3 py-2 space-y-2">
        <div className="flex flex-wrap gap-2 text-[10px] text-muted-foreground">
          <span className="rounded border border-border/40 bg-background/40 px-1.5 py-0.5">
            {caveatCount} caveat{caveatCount === 1 ? "" : "s"}
          </span>
          <span className="rounded border border-border/40 bg-background/40 px-1.5 py-0.5">
            {chartCount} chart{chartCount === 1 ? "" : "s"}
          </span>
        </div>
        {commentPreview && (
          <div>
            <div className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-1">
              Notion comment
            </div>
            <div className="text-xs text-muted-foreground break-words max-h-[120px] overflow-y-auto">
              <MarkdownRenderer content={commentPreview} />
            </div>
          </div>
        )}
        {showRaw && (
          <pre className="text-[11px] leading-relaxed bg-background/60 rounded border border-border/30 p-2 overflow-x-auto max-h-[260px] overflow-y-auto whitespace-pre-wrap break-all font-mono">
            {result.prettyJson}
          </pre>
        )}
      </div>
    </div>
  );
};

/* ── Tool Call Card ── */
const ToolCallCard: React.FC<{ toolCall: AgentToolCall }> = ({ toolCall }) => {
  const [expanded, setExpanded] = useState(false);
  const isRunning = !toolCall.result;
  const isError = toolCall.isError;

  const color = isRunning
    ? { border: "border-l-yellow-500/60", bg: "bg-yellow-500/[0.03]", dot: "bg-yellow-500 animate-pulse", text: "text-yellow-500" }
    : isError
      ? { border: "border-l-red-500/60", bg: "bg-red-500/[0.03]", dot: "bg-red-500", text: "text-red-500" }
      : { border: "border-l-green-500/60", bg: "bg-green-500/[0.03]", dot: "bg-green-500", text: "text-green-500" };

  const isWrite = toolCall.name === "Write" || toolCall.name === "Edit";
  const isRead = toolCall.name === "Read" || toolCall.name === "Glob" || toolCall.name === "Grep";
  const isBash = toolCall.name === "Bash";

  const summary = useMemo(() => {
    const inp = toolCall.input || {};
    if (inp.command) {return String(inp.command).slice(0, 80);}
    if (inp.file_path) {return String(inp.file_path);}
    if (inp.pattern) {return `/${inp.pattern}/`;}
    if (inp.content) {return String(inp.content).split("\n")[0]?.slice(0, 60) || "";}
    return "";
  }, [toolCall.input]);

  const ToolIcon = isWrite
    ? PenLineIcon
    : isBash
      ? PlayIcon
      : isRead
        ? SearchIcon
        : WrenchIcon;

  return (
    <div
      className={cn(
        "rounded-md border border-l-2 overflow-hidden transition-all duration-150 cursor-pointer",
        "hover:border-l-[3px]",
        color.border,
        color.bg,
      )}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Header */}
      <div className="flex items-center gap-2.5 px-3 py-2">
        {isRunning ? (
          <Loader2 className={cn("h-3.5 w-3.5 animate-spin shrink-0", color.text)} />
        ) : (
          <span className={cn("w-2 h-2 rounded-full shrink-0", color.dot)} />
        )}
        <ToolIcon className={cn("h-3.5 w-3.5 shrink-0", color.text)} />
        <span className={cn("text-xs font-semibold", color.text)}>
          {toolCall.name.replace(/^mcp__signalpilot__/, "")}
        </span>
        {isRunning && (
          <span className="text-[10px] text-yellow-500/80 font-medium animate-pulse">
            running...
          </span>
        )}
        {summary && (
          <span className="text-[11px] text-muted-foreground truncate flex-1 min-w-0 font-mono">
            {summary}
          </span>
        )}
        {isRunning && (
          <Loader2 className="h-3 w-3 animate-spin text-muted-foreground ml-auto shrink-0" />
        )}
        {expanded ? (
          <ChevronDownIcon className="h-3 w-3 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRightIcon className="h-3 w-3 text-muted-foreground shrink-0" />
        )}
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="border-t border-border/30 px-3 py-2 space-y-2">
          {toolCall.input && Object.keys(toolCall.input).length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">
                Input
              </div>
              <pre className="text-[11px] leading-relaxed bg-background/50 rounded border border-border/30 p-2 overflow-x-auto max-h-[150px] overflow-y-auto whitespace-pre-wrap break-all font-mono">
                {JSON.stringify(toolCall.input, null, 2)}
              </pre>
            </div>
          )}
          {toolCall.result && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">
                {isError ? "Error" : "Output"}
              </div>
              <pre
                className={cn(
                  "text-[11px] leading-relaxed rounded border p-2 overflow-x-auto max-h-[200px] overflow-y-auto whitespace-pre-wrap break-all font-mono",
                  isError
                    ? "bg-red-500/5 border-red-500/20 text-red-400"
                    : "bg-background/50 border-border/30",
                )}
              >
                {toolCall.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/* ── Chat History Sidebar (ChatGPT/Claude-style) ── */

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import type { StoredChatSession } from "@/hooks/useAgentChat";
import { timeAgo } from "@/utils/dates";
import { MoreHorizontalIcon, MessageSquareIcon } from "lucide-react";

const DATE_GROUPS = [
  { label: "Today", maxDays: 1 },
  { label: "Yesterday", maxDays: 2 },
  { label: "This week", maxDays: 7 },
  { label: "This month", maxDays: 30 },
  { label: "Older", maxDays: Infinity },
] as const;

function groupSessionsByDate(sessions: StoredChatSession[]) {
  const now = Date.now();
  const DAY = 86400000;
  const groups: { label: string; sessions: StoredChatSession[] }[] = [];

  for (const group of DATE_GROUPS) {
    const matching = sessions.filter((s) => {
      const daysAgo = (now - s.updatedAt) / DAY;
      const prevMax = DATE_GROUPS[DATE_GROUPS.indexOf(group) - 1]?.maxDays ?? 0;
      return daysAgo >= prevMax && daysAgo < group.maxDays;
    });
    if (matching.length > 0) {
      groups.push({ label: group.label, sessions: matching });
    }
  }
  return groups;
}

const AgentChatHistorySidebar: React.FC<{
  sessions: StoredChatSession[];
  isLoading?: boolean;
  onLoadSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onRenameSession: (id: string, title: string) => void;
}> = ({ sessions, isLoading, onLoadSession, onDeleteSession, onRenameSession }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const filtered = search.trim()
    ? sessions.filter((s) =>
        s.title.toLowerCase().includes(search.toLowerCase()),
      )
    : sessions;

  const grouped = groupSessionsByDate(
    [...filtered].toSorted((a, b) => b.updatedAt - a.updatedAt),
  );

  const handleStartRename = (session: StoredChatSession) => {
    setEditingId(session.id);
    setEditValue(session.title);
  };

  const handleFinishRename = () => {
    if (editingId && editValue.trim()) {
      onRenameSession(editingId, editValue.trim());
    }
    setEditingId(null);
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Tooltip content="Chat history">
        <SheetTrigger asChild={true}>
          <Button variant="text" size="icon">
            <ClockIcon className="h-4 w-4" />
          </Button>
        </SheetTrigger>
      </Tooltip>
      <SheetContent
        side="left"
        className="w-80 p-0 flex flex-col !bg-background border-r border-border"
      >
        {/* Header */}
        <SheetHeader className="px-4 pt-4 pb-3 border-b border-border">
          <SheetTitle className="text-sm font-semibold tracking-wide">
            Chat History
          </SheetTitle>
        </SheetHeader>

        {/* Search */}
        <div className="px-3 py-2 border-b border-border">
          <div className="relative">
            <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              className="h-8 pl-8 text-xs bg-muted border-border"
              placeholder="Search chats..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center h-32 text-muted-foreground text-xs gap-2">
              <Loader2 className="h-5 w-5 animate-spin opacity-50" />
              Loading chats...
            </div>
          ) : grouped.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 text-muted-foreground text-xs gap-2">
              <MessageSquareIcon className="h-6 w-6 opacity-30" />
              {search ? "No matching chats" : "No chat history yet"}
            </div>
          ) : (
            grouped.map((group) => (
              <div key={group.label}>
                {/* Date group header */}
                <div className="px-4 pt-3 pb-1">
                  <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                    {group.label}
                  </span>
                </div>

                {/* Sessions in group */}
                {group.sessions.map((session) => (
                  <div
                    key={session.id}
                    className={cn(
                      "group flex items-center gap-2 px-3 py-2 mx-1 rounded-md cursor-pointer transition-colors",
                      "hover:bg-accent",
                    )}
                    onClick={() => {
                      if (editingId !== session.id) {
                        onLoadSession(session.id);
                        setOpen(false);
                      }
                    }}
                  >
                    <MessageSquareIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />

                    <div className="flex-1 min-w-0">
                      {editingId === session.id ? (
                        <input
                          type="text"
                          className="w-full text-xs bg-muted border border-border rounded px-1.5 py-0.5 focus:outline-none focus:border-ring"
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onBlur={handleFinishRename}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {handleFinishRename();}
                            if (e.key === "Escape") {setEditingId(null);}
                          }}
                          autoFocus={true}
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <>
                          <div className="text-xs font-medium truncate">
                            {session.title}
                          </div>
                          <div className="text-[10px] text-muted-foreground">
                            {timeAgo(session.updatedAt, navigator.language)}
                          </div>
                        </>
                      )}
                    </div>

                    {/* Actions menu */}
                    {editingId !== session.id && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild={true}>
                          <Button
                            variant="text"
                            size="icon"
                            className="h-6 w-6 opacity-0 group-hover:opacity-100 shrink-0"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <MoreHorizontalIcon className="h-3.5 w-3.5" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-36">
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              handleStartRename(session);
                            }}
                          >
                            <PenLineIcon className="h-3.5 w-3.5 mr-2" />
                            Rename
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteSession(session.id);
                            }}
                          >
                            <Trash2Icon className="h-3.5 w-3.5 mr-2" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
};

export default AgentChatPanel;
