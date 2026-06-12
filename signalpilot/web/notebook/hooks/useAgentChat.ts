import { useCallback, useEffect, useRef, useState } from "react";
import { spApiUrl } from "@/core/network/api";

export interface AgentMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: AgentToolCall[];
  thinking?: string;
  turn?: number;
}

export interface AgentToolCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
  result?: string;
  isError?: boolean;
}

export interface UseAgentChatOptions {
  baseUrl: string;
  headers: () => Record<string, string> | Promise<Record<string, string>>;
  getActiveFile?: () => string | null;
  includeNotionConversations?: boolean;
  initialSessionId?: string | null;
}

export interface UseAgentChatReturn {
  messages: AgentMessage[];
  sendMessage: (text: string) => Promise<void>;
  stopAgent: () => void;
  isStreaming: boolean;
  error: string | null;
  clearMessages: () => void;
}

let messageIdCounter = 0;
function nextId() {
  return `msg-${++messageIdCounter}-${Date.now()}`;
}

// ── Chat session type ───────────────────────────────────────────

export interface StoredChatSession {
  id: string;
  title: string;
  messages: AgentMessage[];
  createdAt: number;
  updatedAt: number;
  source?: string;
  status?: string;
  notebookPath?: string;
}

// ── Gateway chat API helpers ────────────────────────────────────

async function chatFetch(
  path: string,
  hdrs: Record<string, string>,
  opts?: { method?: string; body?: unknown },
): Promise<unknown> {
  const resp = await fetch(spApiUrl(`/chat${path}`), {
    method: opts?.method ?? "GET",
    headers: { "Content-Type": "application/json", ...hdrs },
    body: opts?.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!resp.ok) {return null;}
  const text = await resp.text();
  return text ? JSON.parse(text) : null;
}

function serializeAssistantMsg(msg: AgentMessage): string {
  const meta: Record<string, unknown> = {};
  if (msg.toolCalls?.length) {meta.toolCalls = msg.toolCalls;}
  if (msg.thinking) {meta.thinking = msg.thinking;}
  return JSON.stringify({ content: msg.content, ...meta });
}

function deserializeMessages(
  gwMessages: Array<{ role: string; content: string; metadata_json?: string | null; id: string; created_at: number }>,
): AgentMessage[] {
  const result: AgentMessage[] = [];
  const appendMessage = (message: AgentMessage) => {
    const previous = result.at(-1);
    const hasToolCalls = (message.toolCalls?.length ?? 0) > 0;
    const isToolOnly =
      message.role === "assistant" &&
      hasToolCalls &&
      !message.content.trim() &&
      !message.thinking;
    if (isToolOnly && previous?.role === "assistant") {
      previous.toolCalls = [
        ...(previous.toolCalls ?? []),
        ...(message.toolCalls ?? []),
      ];
      return;
    }
    result.push(message);
  };

  for (const gm of gwMessages) {
    if (gm.role === "user") {
      appendMessage({ id: gm.id, role: "user", content: gm.content });
    } else if (gm.role === "assistant") {
      try {
        const parsed = JSON.parse(gm.content) as { content?: string; toolCalls?: AgentToolCall[]; thinking?: string };
        appendMessage({
          id: gm.id,
          role: "assistant",
          content: parsed.content ?? gm.content,
          toolCalls: parsed.toolCalls,
          thinking: parsed.thinking,
        });
      } catch {
        appendMessage({ id: gm.id, role: "assistant", content: gm.content });
      }
    }
  }
  return result;
}

// ── Hook ────────────────────────────────────────────────────────

export function useAgentChat({
  baseUrl,
  headers,
  getActiveFile,
  includeNotionConversations = false,
  initialSessionId = null,
}: UseAgentChatOptions): UseAgentChatReturn & {
  chatSessions: StoredChatSession[];
  activeSessionId: string | null;
  isLoadingSessions: boolean;
  isLoadingMessages: boolean;
  loadSession: (sessionId: string) => void;
  deleteSession: (sessionId: string) => void;
  renameSession: (sessionId: string, newTitle: string) => void;
} {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // The underlying headers() may be async (e.g. when an auth token must be resolved).
  const getHeaders = useCallback(async (): Promise<Record<string, string>> => {
    return await headers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const instanceIdRef = useRef<string | null>(null);
  const newChatRef = useRef(false);
  const assistantIdRef = useRef("");
  const lastEventWasTextRef = useRef(false);
  const conversationIdRef = useRef<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [chatSessions, setChatSessions] = useState<StoredChatSession[]>([]);

  // Load sessions from gateway on mount
  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    const toSession = (c: Record<string, unknown>): StoredChatSession => ({
      id: c.id as string,
      title: (c.title as string) || "New chat",
      messages: [],
      createdAt: (c.created_at as number) * 1000 || Date.now(),
      updatedAt: (c.updated_at as number) * 1000 || Date.now(),
      source: c.source as string | undefined,
      status: c.status as string | undefined,
      notebookPath: c.notebook_path as string | undefined,
    });
    const mergeConversations = (
      conversations: Array<Record<string, unknown>>,
      next: Array<Record<string, unknown>>,
    ) => {
      const seen = new Set(conversations.map((c) => c.id));
      for (const conversation of next) {
        if (!seen.has(conversation.id)) {
          conversations.push(conversation);
        }
      }
    };

    setIsLoadingSessions(true);
    const loadSessions = async (attempt = 0): Promise<void> => {
      try {
        const hdrs = await getHeaders();
        const data = await chatFetch("/conversations", hdrs);
        const convs =
          (data as { conversations?: Array<Record<string, unknown>> })?.conversations ?? [];
        const conversations = Array.isArray(convs) ? [...convs] : [];

        if (includeNotionConversations) {
          const notionData = await chatFetch("/conversations?source=notion", hdrs);
          const notionConvs =
            (notionData as { conversations?: Array<Record<string, unknown>> })?.conversations ?? [];
          if (Array.isArray(notionConvs)) {
            mergeConversations(conversations, notionConvs);
          }
        }

        if (
          includeNotionConversations &&
          conversations.length === 0 &&
          attempt < 3 &&
          !cancelled
        ) {
          retryTimer = setTimeout(() => {
            retryTimer = null;
            void loadSessions(attempt + 1);
          }, 750 * (attempt + 1));
          return;
        }

        if (!cancelled) {
          setChatSessions(conversations.map(toSession));
        }
      } catch {
        if (includeNotionConversations && attempt < 3 && !cancelled) {
          retryTimer = setTimeout(() => {
            retryTimer = null;
            void loadSessions(attempt + 1);
          }, 750 * (attempt + 1));
          return;
        }
      } finally {
        if (!cancelled && !retryTimer) {
          setIsLoadingSessions(false);
        }
      }
    };

    void loadSessions();
    return () => {
      cancelled = true;
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
    };
  }, [includeNotionConversations]);

  const loadSession = useCallback(
    (sid: string) => {
      setIsLoadingMessages(true);
      setError(null);
      getHeaders().then((hdrs) => chatFetch(`/conversations/${sid}`, hdrs)).then((data) => {
        const detail = data as {
          conversation?: Record<string, unknown>;
          messages?: Array<{ role: string; content: string; metadata_json?: string | null; id: string; created_at: number }>;
        } | null;
        if (!detail?.messages) {
          throw new Error(`Could not load chat thread ${sid}`);
        }
        const msgs = deserializeMessages(detail.messages);
        setMessages(msgs);
        conversationIdRef.current = sid;
        setActiveSessionId(sid);
        newChatRef.current = true;
        instanceIdRef.current = null;
      }).catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      }).finally(() => setIsLoadingMessages(false));
    },
    [getHeaders],
  );

  useEffect(() => {
    if (
      !initialSessionId?.startsWith("session-notion-") ||
      conversationIdRef.current === initialSessionId
    ) {
      return;
    }

    loadSession(initialSessionId);
  }, [initialSessionId, loadSession]);

  const deleteSession = useCallback(
    (sid: string) => {
      getHeaders().then((hdrs) => chatFetch(`/conversations/${sid}`, hdrs, { method: "DELETE" })).then(() => {
        setChatSessions((prev) => prev.filter((s) => s.id !== sid));
        if (conversationIdRef.current === sid) {
          setMessages([]);
          conversationIdRef.current = null;
          setActiveSessionId(null);
          instanceIdRef.current = null;
        }
      }).catch(() => {});
    },
    [headers],
  );

  const renameSession = useCallback(
    (_sid: string, _newTitle: string) => {
      // Gateway doesn't support rename yet — no-op
    },
    [],
  );

  const clearMessages = useCallback(() => {
    conversationIdRef.current = null;
    setActiveSessionId(null);
    instanceIdRef.current = null;
    setMessages([]);
    setError(null);
    newChatRef.current = true;
    assistantIdRef.current = "";
    lastEventWasTextRef.current = false;
  }, []);

  function startNewBlock() {
    assistantIdRef.current = nextId();
    lastEventWasTextRef.current = false;
    setMessages((prev) => [...prev, {
      id: assistantIdRef.current,
      role: "assistant" as const,
      content: "",
      toolCalls: [],
    }]);
  }

  async function ensureInstance(hdrs: Record<string, string>): Promise<string> {
    if (instanceIdRef.current) {return instanceIdRef.current;}

    const resp = await fetch(`${baseUrl}/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...hdrs },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514",
      }),
    });

    if (!resp.ok) {
      throw new Error(`Failed to create agent: HTTP ${resp.status}`);
    }

    const data = await resp.json() as { instanceId: string };
    instanceIdRef.current = data.instanceId;
    return data.instanceId;
  }

  async function ensureConversation(hdrs: Record<string, string>, title: string): Promise<string> {
    if (conversationIdRef.current) {return conversationIdRef.current;}

    const result = await chatFetch("/conversations", hdrs, {
      method: "POST",
      body: { title },
    }) as { id?: string } | null;

    if (!result?.id) {throw new Error("Failed to create conversation");}
    conversationIdRef.current = result.id;
    setActiveSessionId(result.id);

    setChatSessions((prev) => [{
      id: result.id!,
      title,
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }, ...prev]);

    return result.id;
  }

  async function persistMessage(
    hdrs: Record<string, string>,
    convId: string,
    role: string,
    content: string,
  ) {
    await chatFetch(`/conversations/${convId}/messages`, hdrs, {
      method: "POST",
      body: { role, content },
    }).catch(() => {});
  }

  const sendMessage = useCallback(
    async (text: string) => {
      setError(null);
      setIsStreaming(true);

      const userMsg: AgentMessage = {
        id: nextId(),
        role: "user",
        content: text,
      };
      setMessages((prev) => [...prev, userMsg]);

      assistantIdRef.current = nextId();
      lastEventWasTextRef.current = false;

      const assistantMsg: AgentMessage = {
        id: assistantIdRef.current,
        role: "assistant",
        content: "",
        toolCalls: [],
      };
      setMessages((prev) => [...prev, assistantMsg]);

      const abort = new AbortController();
      abortRef.current = abort;

      try {
        const hdrs = await getHeaders();
        const instanceId = await ensureInstance(hdrs);

        const title = text.slice(0, 60) + (text.length > 60 ? "..." : "");
        const convId = await ensureConversation(hdrs, title);

        // Persist user message to gateway
        await persistMessage(hdrs, convId, "user", text);

        const currentMessages = [...messages, userMsg].map((m) => ({
          role: m.role,
          content: m.content,
        }));

        const response = await fetch(`${baseUrl}/message`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...hdrs },
          body: JSON.stringify({
            instanceId,
            message: text,
            newChat: newChatRef.current,
            messageHistory: currentMessages,
            contextFile: getActiveFile?.() || null,
          }),
          signal: abort.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {throw new Error("No response body");}

        const decoder = new TextDecoder();
        let buffer = "";

        let streamDone = false;
        while (!streamDone) {
          const { done, value } = await reader.read();
          if (done) {break;}

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) {continue;}
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) {continue;}

            try {
              const event = JSON.parse(jsonStr) as Parameters<typeof handleEvent>[0];
              if (event.type === "done") {
                streamDone = true;
                break;
              }
              handleEvent(event);
            } catch {
              // Skip malformed events
            }
          }
        }

        // Persist final assistant response to gateway
        setMessages((prev) => {
          const lastAssistant = prev.findLast((m) => m.role === "assistant");
          if (lastAssistant && convId) {
            persistMessage(hdrs, convId, "assistant", serializeAssistantMsg(lastAssistant));
          }
          return prev;
        });
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          const errMsg = (e as Error).message || "Unknown error";
          setError(errMsg);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantIdRef.current
                ? { ...m, content: m.content || `Error: ${errMsg}` }
                : m,
            ),
          );
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
        newChatRef.current = false;
      }
    },
    [baseUrl, headers, messages],
  );

  function handleEvent(event: {
    type: string;
    content?: string;
    tool_name?: string;
    tool_input?: Record<string, unknown>;
    tool_call_id?: string;
    is_error?: boolean;
    cost_usd?: number | null;
    turn?: number;
  }) {
    const assistantId = assistantIdRef.current;
    switch (event.type) {
      case "text_delta":
        lastEventWasTextRef.current = true;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: m.content + (event.content || "") }
              : m,
          ),
        );
        break;

      case "text":
        lastEventWasTextRef.current = true;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: event.content || "" }
              : m,
          ),
        );
        break;

      case "thinking_delta":
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, thinking: (m.thinking || "") + (event.content || "") }
              : m,
          ),
        );
        break;

      case "thinking":
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, thinking: event.content || "" }
              : m,
          ),
        );
        break;

      case "block_start":
        break;

      case "tool_use": {
        const currentId = assistantIdRef.current;
        const toolCall: AgentToolCall = {
          id: event.tool_call_id || nextId(),
          name: event.tool_name || "",
          input: event.tool_input || {},
        };

        setMessages((prev) =>
          prev.map((m) =>
            m.id === currentId
              ? { ...m, toolCalls: [...(m.toolCalls || []), toolCall] }
              : m,
          ),
        );
        break;
      }

      case "tool_result":
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== assistantId) {return m;}
            const toolCalls = [...(m.toolCalls || [])];
            const targetId = event.tool_call_id;
            let matched = false;
            if (targetId) {
              for (const tc of toolCalls) {
                if (tc.id === targetId && !tc.result) {
                  tc.result = event.content || "";
                  tc.isError = event.is_error;
                  matched = true;
                  break;
                }
              }
            }
            if (!matched) {
              const lastTc = toolCalls.findLast((tc) => !tc.result);
              if (lastTc) {
                lastTc.result = event.content || "";
                lastTc.isError = event.is_error;
              }
            }
            return { ...m, toolCalls };
          }),
        );
        break;

      case "error":
        setError(event.content || "Unknown error");
        break;

      case "done":
        break;
    }
  }

  const stopAgent = useCallback(() => {
    if (!abortRef.current) {return;}

    abortRef.current.abort();
    abortRef.current = null;

    if (instanceIdRef.current) {
      const instanceId = instanceIdRef.current;
      getHeaders().then((hdrs) => {
        fetch(`${baseUrl}/stop`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...hdrs },
          body: JSON.stringify({ instanceId }),
        }).catch(() => {});
      }).catch(() => {});
    }

    setIsStreaming(false);

    if (assistantIdRef.current) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantIdRef.current
            ? { ...m, content: m.content || "Stopped." }
            : m,
        ),
      );
    }
  }, [baseUrl, headers]);

  return {
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
  };
}
