"use client";

import { createContext, useContext } from "react";

export type ChatTelemetryContextValue = {
  enabled: boolean;
  nowMs: number;
};

export const ChatTelemetryContext = createContext<ChatTelemetryContextValue>({
  enabled: false,
  nowMs: 0,
});

export function useChatTelemetryContext() {
  return useContext(ChatTelemetryContext);
}
