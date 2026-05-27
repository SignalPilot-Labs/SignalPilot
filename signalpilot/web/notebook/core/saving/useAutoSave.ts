import { useEffect, useRef } from "react";
import type { UserConfig } from "../config/config-schema";
import type { CellConfig } from "../network/types";
import { type ConnectionStatus, WebSocketState } from "../websocket/types";

export function useAutoSave(opts: {
  codes: string[];
  cellConfigs: CellConfig[];
  cellNames: string[];
  config: UserConfig["save"];
  connStatus: ConnectionStatus;
  needsSave: boolean;
  kioskMode: boolean;
  onSave: () => void;
  filename?: string | null;
}) {
  const {
    codes,
    cellConfigs,
    config,
    connStatus,
    cellNames,
    needsSave,
    kioskMode,
    onSave,
    filename,
  } = opts;
  const autosaveTimeoutId = useRef<NodeJS.Timeout | null>(null);
  // Capture the filename at the time autosave is scheduled
  const scheduledFilenameRef = useRef<string | null | undefined>(null);

  const codesString = codes.join(":");
  const cellConfigsString = cellConfigs
    .map((config) => JSON.stringify(config))
    .join(":");
  const cellNamesString = cellNames.join(":");

  useEffect(() => {
    // If kiosk mode is enabled, do not autosave
    if (kioskMode) {
      return;
    }

    if (config.autosave === "after_delay") {
      if (autosaveTimeoutId.current !== null) {
        clearTimeout(autosaveTimeoutId.current);
      }

      if (needsSave && connStatus.state === WebSocketState.OPEN) {
        // Capture current filename when scheduling
        scheduledFilenameRef.current = filename;
        autosaveTimeoutId.current = setTimeout(() => {
          // DEFENSE: Only save if filename hasn't changed since scheduling
          if (scheduledFilenameRef.current === filename) {
            onSave();
          }
        }, config.autosave_delay);
      }
    }

    return () => {
      if (autosaveTimeoutId.current !== null) {
        clearTimeout(autosaveTimeoutId.current);
      }
    };
  }, [
    codesString,
    cellConfigsString,
    cellNamesString,
    config,
    connStatus.state,
    onSave,
    kioskMode,
    needsSave,
    filename,
  ]);
}
