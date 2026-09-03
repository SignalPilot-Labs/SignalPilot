"use client";

import { useEffect, useRef, useState } from "react";
import type { StandaloneChatBootstrap } from "~/lib/api";
import type { ChatBudgetSettings } from "~/components/chat/chat-settings-panel";

export function useChatBudgetSettings(
  bootstrap: StandaloneChatBootstrap | undefined,
  conversationId: string | undefined,
): {
  perQueryBudgetUsd: number;
  chatBudgetUsd: number;
  budgetSettings: ChatBudgetSettings | null;
} {
  const [perQueryBudgetUsd, setPerQueryBudgetUsd] = useState(0.25);
  const [chatBudgetUsd, setChatBudgetUsd] = useState(1);
  const initialized = useRef(false);

  useEffect(() => {
    if (!bootstrap || initialized.current) return;
    setPerQueryBudgetUsd(bootstrap.default_per_query_budget_usd);
    setChatBudgetUsd(bootstrap.default_chat_budget_usd);
    initialized.current = true;
  }, [bootstrap]);

  return {
    perQueryBudgetUsd,
    chatBudgetUsd,
    budgetSettings:
      !conversationId && bootstrap?.enterprise_features.query_approval
        ? {
            perQueryBudgetUsd,
            setPerQueryBudgetUsd,
            chatBudgetUsd,
            setChatBudgetUsd,
          }
        : null,
  };
}
