import { useAtomValue } from "jotai";
import { HardDriveDownloadIcon, PlayIcon } from "lucide-react";
import type { JSX } from "react";
import { Spinner } from "@/components/icons/spinner";
import type { CellConfig, RuntimeState } from "@/core/network/types";
import { useRuntimeManager } from "@/core/runtime/config";
import {
  isKernelLaunchInFlight,
  kernelLaunchAtom,
} from "@/core/runtime/launch-state";
import {
  getConnectionTooltip,
  isAppInteractionDisabled,
} from "@/core/websocket/connection-utils";
import { WebSocketState } from "@/core/websocket/types";
import { renderShortcut } from "../../shortcuts/renderShortcut";
import { ToolbarItem } from "./toolbar";

function computeColor({
  appInteractionDisabled,
  needsRun,
  loading,
  inactive,
}: {
  appInteractionDisabled: boolean;
  needsRun: boolean;
  loading: boolean;
  inactive: boolean;
}) {
  if (appInteractionDisabled) {
    return "disabled";
  }
  if (needsRun && !loading) {
    return "stale";
  }
  if (loading || inactive) {
    return "disabled";
  }
  return "green";
}

export const RunButton = (props: {
  edited: boolean;
  status: RuntimeState;
  needsRun: boolean;
  connectionState: WebSocketState;
  config: CellConfig;
  onClick?: () => void;
}): JSX.Element => {
  const { onClick, connectionState, needsRun, status, config, edited } = props;

  const launch = useAtomValue(kernelLaunchAtom);
  const isLazy = useRuntimeManager().isLazy;
  const launching = isKernelLaunchInFlight(launch);
  // Lazy runtime, kernel not up yet: the run flow itself brings the kernel
  // up (and queues this run behind an in-flight launch), so the button must
  // stay clickable — a dead Play button here reads as "broken".
  const lazyPreKernel =
    isLazy &&
    (connectionState === WebSocketState.NOT_STARTED ||
      (connectionState === WebSocketState.CONNECTING && launching));

  const appInteractionDisabled =
    isAppInteractionDisabled(connectionState) && !lazyPreKernel;
  const blockedStatus = status === "disabled-transitively";
  const loading = status === "running" || status === "queued";
  const inactive =
    appInteractionDisabled ||
    loading ||
    (!config.disabled && blockedStatus && !edited);
  const variant = computeColor({
    appInteractionDisabled,
    needsRun,
    loading,
    inactive,
  });

  if (config.disabled) {
    return (
      <ToolbarItem
        tooltip="Add code to notebook"
        disabled={inactive}
        onClick={onClick}
        variant={variant}
        data-testid="run-button"
      >
        <HardDriveDownloadIcon />
      </ToolbarItem>
    );
  }
  if (!config.disabled && blockedStatus && !edited) {
    return (
      <ToolbarItem
        disabled={inactive}
        tooltip="This cell can't be run because it has a disabled ancestor"
        onClick={onClick}
        variant={variant}
        data-testid="run-button"
      >
        <PlayIcon strokeWidth={1.2} />
      </ToolbarItem>
    );
  }

  let tooltipMsg: React.ReactNode = "";

  if (lazyPreKernel) {
    tooltipMsg = launching
      ? "Kernel is starting — your run begins the moment it's ready"
      : renderShortcut("cell.run");
  } else if (appInteractionDisabled) {
    tooltipMsg = getConnectionTooltip(connectionState);
  } else if (status === "queued") {
    tooltipMsg = "This cell is already queued to run";
  } else if (status === "running") {
    tooltipMsg = "This cell is already running.";
  } else {
    tooltipMsg = renderShortcut("cell.run");
  }

  return (
    <ToolbarItem
      tooltip={tooltipMsg}
      disabled={inactive}
      onClick={onClick}
      variant={variant}
      data-testid="run-button"
    >
      {lazyPreKernel && launching && launch.trigger === "run" ? (
        <Spinner size="small" className="size-3" />
      ) : (
        <PlayIcon strokeWidth={1.2} />
      )}
    </ToolbarItem>
  );
};
