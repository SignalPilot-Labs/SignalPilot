"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { StandaloneChatEvent, StandaloneChatRun } from "~/lib/api";
import { activeDashboardAuthoringProgress } from "~/lib/chat-run-steps";
import type { UiMessage } from "~/components/chat/chat-ui-context";

/**
 * Open/close state for the chat's dashboard preview panel. The open session
 * is mirrored into the `?dashboard=` search param so a refresh or a shared
 * link lands on the same preview. A run that produces a preview opens the
 * panel once on its own; `onOpen` runs first so sibling panels in the
 * right-hand slot can tuck away.
 */
export function useChatDashboardPanel({
  conversationId,
  uiMessages,
  events,
  currentRun,
  onOpen,
}: {
  conversationId: string | undefined;
  uiMessages: UiMessage[];
  events: StandaloneChatEvent[];
  currentRun: StandaloneChatRun | null;
  onOpen: () => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [sessionId, setSessionId] = useState<string | null>(
    searchParams.get("dashboard"),
  );
  // The last session shown, so a sibling panel can hand the slot back.
  const lastSessionId = useRef<string | null>(sessionId);
  const autoOpened = useRef<string | null>(null);
  const observedActiveRun = useRef(false);
  useEffect(() => {
    observedActiveRun.current = false;
    autoOpened.current = null;
  }, [conversationId]);

  // The param value this hook last wrote or applied. Only a NEW value from
  // the outside (a pasted link, a message card's navigation) opens the panel,
  // so a settings dismissal does not bounce straight back.
  const appliedParam = useRef(searchParams.get("dashboard"));
  const replaceParam = useCallback(
    (value: string | null) => {
      appliedParam.current = value;
      const params = new URLSearchParams(searchParams.toString());
      if (value) params.set("dashboard", value);
      else params.delete("dashboard");
      const query = params.toString();
      router.replace(`${window.location.pathname}${query ? `?${query}` : ""}`);
    },
    [router, searchParams],
  );

  const open = useCallback(
    (nextSessionId: string) => {
      onOpen();
      lastSessionId.current = nextSessionId;
      setSessionId(nextSessionId);
      replaceParam(nextSessionId);
    },
    [onOpen, replaceParam],
  );
  const close = useCallback(() => {
    setSessionId(null);
    replaceParam(null);
  }, [replaceParam]);
  // Hide the panel without forgetting the session (settings takes the slot).
  const dismiss = useCallback(() => setSessionId(null), []);
  const reopen = useCallback(() => {
    if (lastSessionId.current) open(lastSessionId.current);
  }, [open]);

  useEffect(() => {
    const requested = searchParams.get("dashboard");
    if (requested === appliedParam.current) return;
    appliedParam.current = requested;
    if (requested) {
      onOpen();
      lastSessionId.current = requested;
      setSessionId(requested);
    }
  }, [onOpen, searchParams]);

  const messageSessionId = useMemo(() => {
    for (let index = uiMessages.length - 1; index >= 0; index -= 1) {
      const preview = uiMessages[index]?.metadata?.dashboard_preview;
      if (preview && typeof preview === "object") {
        const id = (preview as Record<string, unknown>).authoring_session_id;
        if (typeof id === "string" && id) return id;
      }
    }
    return null;
  }, [uiMessages]);
  const progress = useMemo(
    () => activeDashboardAuthoringProgress(events, currentRun?.id),
    [currentRun?.id, events],
  );
  const latestSessionId = messageSessionId ?? progress?.sessionId ?? null;
  const updateLabel =
    progress?.phase === "ready" ? null : (progress?.label ?? null);

  useEffect(() => {
    if (currentRun?.status === "queued" || currentRun?.status === "running") {
      observedActiveRun.current = true;
    }
    if (
      latestSessionId &&
      observedActiveRun.current &&
      autoOpened.current !== latestSessionId
    ) {
      autoOpened.current = latestSessionId;
      open(latestSessionId);
    }
  }, [currentRun?.status, latestSessionId, open]);

  return {
    sessionId,
    latestSessionId,
    updateLabel,
    updateRevision: progress?.draftRevision ?? 0,
    open,
    close,
    dismiss,
    reopen,
  };
}
