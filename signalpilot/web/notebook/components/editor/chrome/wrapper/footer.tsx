import { useAtomValue } from "jotai";
import {
  AlertTriangleIcon,
  ChevronUpIcon,
  TerminalSquareIcon,
  XCircleIcon,
} from "lucide-react";
import type React from "react";
import { renderShortcut } from "@/components/shortcuts/renderShortcut";
import { Tooltip } from "@/components/ui/tooltip";
import { cellErrorCount } from "@/core/cells/cells";
import { capabilitiesAtom } from "@/core/config/capabilities";
import { isConnectingAtom } from "@/core/network/connection";
import { useHotkey } from "@/hooks/useHotkey";
import { cn } from "@/utils/cn";
import { ShowInKioskMode } from "../../kiosk-mode";
import { panelLayoutAtom, useChromeActions, useChromeState } from "../state";
import { FooterItem } from "./footer-item";
import {
  BackendConnectionStatus,
  connectionStatusAtom,
} from "./footer-items/backend-status";
import { MachineStats } from "./footer-items/machine-stats";


import { RuntimeSettings } from "./footer-items/runtime-settings";
import { useSetDependencyPanelTab } from "./useDependencyPanelTab";

export const Footer: React.FC = () => {
  const { isDeveloperPanelOpen, selectedDeveloperPanelTab } = useChromeState();
  const { toggleDeveloperPanel, toggleApplication, openApplication } =
    useChromeActions();
  const setDependencyPanelTab = useSetDependencyPanelTab();
  const capabilities = useAtomValue(capabilitiesAtom);

  const errorCount = useAtomValue(cellErrorCount);
  const connectionStatus = useAtomValue(connectionStatusAtom);
  const panelLayout = useAtomValue(panelLayoutAtom);

  // Show issue count: cell errors + connection issues
  // Don't include error count if errors panel is in sidebar (it shows there instead)
  const errorsInSidebar = panelLayout.sidebar.includes("errors");
  const hasConnectionIssue =
    connectionStatus === "unhealthy" || connectionStatus === "disconnected";
  const issueCount =
    (errorsInSidebar ? 0 : errorCount) + (hasConnectionIssue ? 1 : 0);

  // TODO: Add warning count from diagnostics/linting
  // This can signal warnings/errors with settings up AI / Copilot etc
  const warningCount = 0;

  const terminalIsActive =
    isDeveloperPanelOpen && selectedDeveloperPanelTab === "terminal";

  useHotkey("global.toggleTerminal", () => {
    toggleApplication("terminal");
  });

  useHotkey("global.togglePanel", () => {
    toggleDeveloperPanel();
  });

  useHotkey("global.toggleMinimap", () => {
    toggleApplication("dependencies");
    setDependencyPanelTab("minimap");
  });

  return (
    <footer className="h-10 py-1 gap-1 bg-background flex items-center text-muted-foreground text-md pl-2 pr-1 border-t border-border select-none print:hidden text-sm z-50 hide-on-fullscreen overflow-x-auto overflow-y-hidden scrollbar-thin">
      <FooterItem
        className="h-full"
        tooltip={
          <span className="flex items-center gap-2">
            Toggle developer panel {renderShortcut("global.togglePanel", false)}
          </span>
        }
        selected={isDeveloperPanelOpen}
        onClick={() => toggleDeveloperPanel()}
        data-testid="footer-panel"
      >
        <div className="flex items-center gap-1 h-full">
          <XCircleIcon
            className={`w-4 h-4 ${issueCount > 0 ? "text-destructive" : ""}`}
          />
          <span>{issueCount}</span>
          <AlertTriangleIcon
            className={`w-4 h-4 ml-1 ${warningCount > 0 ? "text-yellow-500" : ""}`}
          />
          <span>{warningCount}</span>
        </div>
      </FooterItem>

      <RuntimeSettings />

      {capabilities.terminal && (
        <Tooltip
          content={
            <span className="flex items-center gap-2">
              Toggle terminal{" "}
              {renderShortcut("global.toggleTerminal", false)}
            </span>
          }
          side="top"
          delayDuration={200}
        >
          <button
            type="button"
            className={cn(
              "flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium transition-all cursor-pointer",
              "border border-border",
              terminalIsActive
                ? "bg-primary/15 text-primary border-primary/30"
                : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
            onClick={() => openApplication("terminal")}
          >
            <TerminalSquareIcon className="w-3.5 h-3.5" />
            <span>Terminal</span>
            <ChevronUpIcon
              className={cn(
                "w-3 h-3 transition-transform",
                terminalIsActive && "rotate-180",
              )}
            />
          </button>
        </Tooltip>
      )}

      <div className="flex-1" />

      <ConnectingKernelIndicatorItem />

      <ShowInKioskMode>
        <Tooltip
          content={
            <div className="w-[200px]">
              Kiosk mode is enabled. This allows you to view the outputs of the
              cells without the ability to edit them.
            </div>
          }
        >
          <span className="text-muted-foreground text-sm mr-4">kiosk mode</span>
        </Tooltip>
      </ShowInKioskMode>

      <div className="flex items-center shrink-0 min-w-0">
        <MachineStats />
      </div>
    </footer>
  );
};

/**
 * Only show the backend connection status if we are connecting to a kernel
 */
const ConnectingKernelIndicatorItem: React.FC = () => {
  const isConnecting = useAtomValue(isConnectingAtom);
  if (!isConnecting) {
    return null;
  }
  return <BackendConnectionStatus />;
};
