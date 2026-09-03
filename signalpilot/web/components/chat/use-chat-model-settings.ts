"use client";

import { useCallback, useEffect, useState } from "react";
import {
  updateStandaloneConversationEffort,
  updateStandaloneConversationModel,
  type StandaloneChatEffort,
  type StandaloneChatEffortOption,
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
  conversationEffort,
  defaultModel,
  defaultEffort,
  options,
  effortOptions,
  runStatus,
  mutateDetail,
}: {
  conversationId?: string;
  conversationModel?: StandaloneChatModel;
  conversationEffort?: StandaloneChatEffort;
  defaultModel?: StandaloneChatModel;
  defaultEffort?: StandaloneChatEffort;
  options: StandaloneChatModelOption[];
  effortOptions: StandaloneChatEffortOption[];
  runStatus?: StandaloneChatRunStatus;
  mutateDetail: DetailMutator;
}): {
  selectedModel: StandaloneChatModel;
  selectedEffort: StandaloneChatEffort;
  modelSettings: ChatModelSettings;
} {
  const { toast } = useToast();
  const [selectedModel, setSelectedModel] =
    useState<StandaloneChatModel>("claude-opus-4-6");
  const [selectedEffort, setSelectedEffort] =
    useState<StandaloneChatEffort>("medium");

  useEffect(() => {
    if (conversationModel) setSelectedModel(conversationModel);
    else if (!conversationId && defaultModel) setSelectedModel(defaultModel);
  }, [conversationId, conversationModel, defaultModel]);

  useEffect(() => {
    if (conversationEffort) setSelectedEffort(conversationEffort);
    else if (!conversationId && defaultEffort) setSelectedEffort(defaultEffort);
  }, [conversationEffort, conversationId, defaultEffort]);

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

  const onEffortChange = useCallback(
    (effort: StandaloneChatEffort) => {
      const previous = selectedEffort;
      setSelectedEffort(effort);
      if (!conversationId) return;
      void updateStandaloneConversationEffort(conversationId, effort)
        .then(() =>
          mutateDetail(
            (current) =>
              current
                ? {
                    ...current,
                    conversation: { ...current.conversation, effort },
                  }
                : current,
            { revalidate: false },
          ),
        )
        .catch((error) => {
          setSelectedEffort(previous);
          toast(
            error instanceof Error
              ? error.message
              : "Could not change thinking level",
            "error",
          );
        });
    },
    [conversationId, mutateDetail, selectedEffort, toast],
  );

  return {
    selectedModel,
    selectedEffort,
    modelSettings: {
      value: selectedModel,
      options,
      disabled: runStatus === "queued" || runStatus === "running",
      onChange,
      effort: selectedEffort,
      effortOptions,
      onEffortChange,
    },
  };
}
