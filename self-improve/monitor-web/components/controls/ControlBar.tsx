"use client";

import { useState } from "react";
import type { RunStatus } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import {
  PauseIcon,
  PlayIcon,
  StopIcon,
  XCircleIcon,
  LockOpenIcon,
  ChatBubbleBottomCenterTextIcon,
} from "@heroicons/react/16/solid";

interface ControlBarProps {
  status: RunStatus | null;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onKill: () => void;
  onUnlock: () => void;
  onToggleInject: () => void;
  busy: boolean;
  sessionLocked: boolean;
  timeRemaining: string | null;
}

export function ControlBar({
  status,
  onPause,
  onResume,
  onStop,
  onKill,
  onUnlock,
  onToggleInject,
  busy,
  sessionLocked,
  timeRemaining,
}: ControlBarProps) {
  const [showKillConfirm, setShowKillConfirm] = useState(false);

  const isActive = ["running", "paused", "rate_limited"].includes(status || "");
  const canPause = status === "running";
  const canResume = status === "paused";
  const canInject = ["running", "paused"].includes(status || "");

  const handleKill = () => {
    if (!showKillConfirm) {
      setShowKillConfirm(true);
      setTimeout(() => setShowKillConfirm(false), 3000);
      return;
    }
    onKill();
    setShowKillConfirm(false);
  };

  return (
    <div className="flex items-center gap-2">
      {sessionLocked && timeRemaining && (
        <span className="text-[10px] text-amber-400/70 tabular-nums mr-1">
          {timeRemaining} locked
        </span>
      )}

      <Button
        variant="warning"
        disabled={!canPause || busy}
        onClick={onPause}
        icon={<PauseIcon className="h-3 w-3" />}
      >
        Pause
      </Button>

      <Button
        variant="success"
        disabled={!canResume || busy}
        onClick={onResume}
        icon={<PlayIcon className="h-3 w-3" />}
      >
        Resume
      </Button>

      {sessionLocked && (
        <Button
          variant="warning"
          disabled={!isActive || busy}
          onClick={onUnlock}
          icon={<LockOpenIcon className="h-3 w-3" />}
        >
          Unlock
        </Button>
      )}

      <Button
        variant="danger"
        disabled={!isActive || busy}
        onClick={onStop}
        icon={<StopIcon className="h-3 w-3" />}
      >
        Stop
      </Button>

      <Button
        variant="danger"
        disabled={!isActive || busy}
        onClick={handleKill}
        icon={<XCircleIcon className="h-3 w-3" />}
        className={showKillConfirm ? "!bg-red-500/30 !border-red-500/40 animate-pulse" : ""}
      >
        {showKillConfirm ? "Confirm Kill" : "Kill"}
      </Button>

      <div className="w-px h-5 bg-white/[0.06] mx-1" />

      <Button
        variant="primary"
        disabled={!canInject || busy}
        onClick={onToggleInject}
        icon={<ChatBubbleBottomCenterTextIcon className="h-3 w-3" />}
      >
        Inject Prompt
      </Button>
    </div>
  );
}
