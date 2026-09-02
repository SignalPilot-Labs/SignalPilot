"use client";

import { useCallback, useEffect, useState } from "react";
import {
  updateStandaloneConversationModel,
  type StandaloneChatModel,
  type StandaloneChatModelOption,
  type StandaloneChatRunStatus,
} from "~/lib/api";
import type { ChatModelSettings } from "~/components/chat/chat-settings-panel";
import type { DetailMutator } from "~/components/chat/use-standalone-chat-run";
import { useToast } from "~/components/ui/toast";

export function useChatModelSettings({
  conversationId,
  conversationModel,
  defaultModel,
  options,
  runStatus,
  mutateDetail,
}: {
  conversationId?: string;
  conversationModel?: StandaloneChatModel;
  defaultModel?: StandaloneChatModel;
  options: StandaloneChatModelOption[];
  runStatus?: StandaloneChatRunStatus;
  mutateDetail: DetailMutator;
}): { selectedModel: StandaloneChatModel; modelSettings: ChatModelSettings } {
  const { toast } = useToast();
  const [selectedModel, setSelectedModel] =
    useState<StandaloneChatModel>("claude-opus-4-6");

  useEffect(() => {
    if (conversationModel) setSelectedModel(conversationModel);
    else if (!conversationId && defaultModel) setSelectedModel(defaultModel);
  }, [conversationId, conversationModel, defaultModel]);

  const onChange = useCallback(
    (model: StandaloneChatModel) => {
      const previous = selectedModel;
      setSelectedModel(model);
      if (!conversationId) return;
      void updateStandaloneConversationModel(conversationId, model)
        .then(() =>
          mutateDetail(
            (current) =>
              current
                ? {
                    ...current,
                    conversation: { ...current.conversation, model },
                  }
                : current,
            { revalidate: false },
          ),
        )
        .catch((error) => {
          setSelectedModel(previous);
          toast(
            error instanceof Error ? error.message : "Could not change model",
            "error",
          );
        });
    },
    [conversationId, mutateDetail, selectedModel, toast],
  );

  return {
    selectedModel,
    modelSettings: {
      value: selectedModel,
      options,
      disabled: runStatus === "queued" || runStatus === "running",
      onChange,
    },
  };
}
