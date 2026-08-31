import { useAtomValue } from "jotai";
import type React from "react";
import { Spinner } from "@/components/icons/spinner";
import { Tooltip } from "@/components/ui/tooltip";
import { connectionAtom } from "@/core/network/connection";
import { useRuntimeManager } from "@/core/runtime/config";
import {
  isKernelLaunchInFlight,
  kernelLaunchAtom,
  launchRuntime,
} from "@/core/runtime/launch-state";
import { WebSocketState } from "@/core/websocket/types";
import { cn } from "@/utils/cn";

/**
 * Persistent kernel chip for the footer — the always-there, glanceable
 * counterpart to the kernel status island. One dot, one word:
 *
 *   idle (lazy)   · "on demand"  — nothing running, click or Run to start
 *   launching     · live phase   — mirrors the launch state machine
 *   connected     · "ready"      — green, breathing
 *   disconnected  · "offline"    — click to reconnect
 */

const PHASE_LABEL: Record<string, string> = {
  provisioning: "Provisioning sandbox…",
  connecting: "Connecting…",
  starting: "Starting kernel…",
};

export const KernelFooterStatus: React.FC = () => {
  const connection = useAtomValue(connectionAtom).state;
  const launch = useAtomValue(kernelLaunchAtom);
  const isLazy = useRuntimeManager().isLazy;

  const launching = isKernelLaunchInFlight(launch);
  const connected = connection === WebSocketState.OPEN;
  const idleLazy =
    isLazy && !launching && connection === WebSocketState.NOT_STARTED;

  let dot: React.ReactNode;
  let label: string;
  let tooltip: string;

  if (launching) {
    dot = <Spinner size="small" className="size-3 text-primary" />;
    label = PHASE_LABEL[launch.phase] ?? "Starting…";
    tooltip =
      launch.trigger === "prewarm"
        ? "Warming a kernel in the background so your first run is instant"
        : "Bringing up an isolated cloud sandbox for this notebook";
  } else if (connected) {
    dot = (
      <span className="relative flex size-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-(--grass-9) opacity-40 [animation-duration:2.5s]" />
        <span className="relative inline-flex size-2 rounded-full bg-(--grass-9)" />
      </span>
    );
    label = "Kernel ready";
    tooltip = "Connected — runs execute immediately";
  } else if (idleLazy) {
    dot = <span className="size-2 rounded-full border border-muted-foreground/50" />;
    label = "Kernel on demand";
    tooltip = "Starts automatically on your first run — or click to start it now";
  } else {
    dot = <span className="size-2 rounded-full bg-(--red-9)" />;
    label = "Kernel offline";
    tooltip = "Disconnected — click to start a new kernel";
  }

  const clickable = idleLazy || (!launching && !connected);

  return (
    <Tooltip content={tooltip} side="top" delayDuration={200}>
      <button
        type="button"
        data-testid="kernel-footer-status"
        onClick={
          clickable ? () => void launchRuntime("manual").catch(() => {}) : undefined
        }
        className={cn(
          "flex items-center gap-2 rounded-md px-2.5 py-1 text-xs text-muted-foreground transition-colors",
          clickable ? "hover:bg-accent hover:text-foreground cursor-pointer" : "cursor-default",
        )}
      >
        {dot}
        <span className="whitespace-nowrap">{label}</span>
      </button>
    </Tooltip>
  );
};
