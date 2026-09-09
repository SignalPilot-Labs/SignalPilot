import { useEffect, useState } from "react";
import { app, callTool } from "./bridge";
import { applyHostContext } from "./host-theme";
import { mergeEvents } from "./pulse-state";
import { isActive, isTerminal, type Message, type View } from "./types";

type Page = Omit<View, "received_at">;

/**
 * Polls `read_signalpilot_chat_view` for the thread the host handed us and
 * keeps one merged View. Cadence: 50 ms while catching up, 2 s while the run
 * is active, 5 s while it waits for the user, stop once terminal.
 */
export function useRunView() {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let generation = 0;
    let target = "";
    let cursor = 0;
    let messageCursor = 0;
    let runId: string | undefined;

    const poll = async (threadId: string, currentGeneration: number) => {
      if (disposed || currentGeneration !== generation) return;
      if (document.hidden) {
        timer = setTimeout(() => void poll(threadId, currentGeneration), 3000);
        return;
      }
      let delay = 2000;
      try {
        const page = await callTool<Page>("read_signalpilot_chat_view", {
          thread_id: threadId,
          after_sequence: cursor,
          after_message_sequence: messageCursor,
          ...(runId ? { run_id: runId } : {}),
        });
        if (disposed || currentGeneration !== generation) return;
        const sameRun = runId === page.run_id;
        runId = page.run_id;
        cursor = page.next_sequence;
        messageCursor = page.next_message_sequence;
        setView((old) => ({
          ...page,
          received_at: Date.now(),
          events: mergeEvents(old && sameRun ? old.events : [], page.events),
          messages: mergeMessages(old?.messages ?? [], page.messages),
        }));
        setError("");
        const more = page.has_more || page.has_more_messages;
        if (isTerminal(page.status) && !more) return;
        delay = more ? 50 : isActive(page.status) ? 2000 : 5000;
        if (!more && !isActive(page.status)) {
          // Waiting for the user: a follow-up starts a new run, so re-resolve it.
          runId = undefined;
          cursor = 0;
        }
      } catch (cause) {
        if (disposed || currentGeneration !== generation) return;
        setError(cause instanceof Error ? cause.message : "Unable to refresh SignalPilot.");
        delay = 10000;
      }
      if (!disposed && currentGeneration === generation) {
        timer = setTimeout(() => void poll(threadId, currentGeneration), delay);
      }
    };

    app.ontoolresult = (result) => {
      const data = result.structuredContent as Partial<Page> | undefined;
      if (!data?.thread_id || disposed) return;
      if (data.thread_id === target && data.run_id === runId) return;
      target = data.thread_id;
      generation += 1;
      clearTimeout(timer);
      cursor = 0;
      messageCursor = 0;
      runId = data.run_id;
      setView({
        thread_id: data.thread_id,
        run_id: data.run_id ?? "",
        chat_url: data.chat_url ?? "",
        status: data.status ?? "queued",
        events: [],
        messages: [],
        next_sequence: 0,
        next_message_sequence: 0,
        has_more: false,
        has_more_messages: false,
        received_at: Date.now(),
      });
      void poll(target, generation);
    };
    app.onhostcontextchanged = (context) => applyHostContext(context);
    app.onteardown = async () => {
      disposed = true;
      clearTimeout(timer);
      return {};
    };
    void app
      .connect()
      .then(() => {
        applyHostContext(app.getHostContext());
        if (!disposed) setConnected(true);
      })
      .catch((cause) => setError(String(cause)));
    return () => {
      disposed = true;
      clearTimeout(timer);
      void app.close();
    };
  }, []);

  return { view, error, connected };
}

function mergeMessages(existing: Message[], incoming: Message[]): Message[] {
  if (!incoming.length) return existing;
  const byId = new Map(existing.map((message) => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence);
}
