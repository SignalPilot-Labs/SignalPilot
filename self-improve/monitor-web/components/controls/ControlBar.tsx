"use client";

import { useState } from "react";
import type { RunStatus } from "@/lib/types";
import { Button } from "@/components/ui/Button";

interface ControlBarProps {
  status: RunStatus | null;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onKill: () => void;
  onUnlock: () => void;
  onToggleInject: () => void;
  onResumeRun: () => void;
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
  onResumeRun,
  busy,
  sessionLocked,
  timeRemaining,
}: ControlBarProps) {
  const [showKillConfirm, setShowKillConfirm] = useState(false);

  const isActive = ["running", "paused", "rate_limited"].includes(status || "");
  const canPause = status === "running";
  const canResume = status === "paused";
  const canInject = ["running", "paused"].includes(status || "");
  const canResumeRun = ["stopped", "crashed", "error", "rate_limited", "completed", "killed"].includes(status || "");

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
    <div className="flex items-center gap-1.5">
      {sessionLocked && timeRemaining && (
        <span className="text-[10px] text-[#ffaa00]/80 tabular-nums mr-1 flex items-center gap-1">
          <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="#ffaa00" strokeWidth="1" opacity="0.5">
            <rect x="1.5" y="4" width="5" height="3" rx="0.5" />
            <path d="M2.5 4V3a1.5 1.5 0 013 0v1" />
          </svg>
          {timeRemaining}
        </span>
      )}

      <Button
        variant="warning"
        disabled={!canPause || busy}
        onClick={onPause}
        icon={
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="2" width="2" height="6" rx="0.5" />
            <rect x="6" y="2" width="2" height="6" rx="0.5" />
          </svg>
        }
      >
        Pause
      </Button>

      <Button
        variant="success"
        disabled={!canResume || busy}
        onClick={onResume}
        icon={
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <polygon points="3 2 8 5 3 8" />
          </svg>
        }
      >
        Resume
      </Button>

      {sessionLocked && (
        <Button
          variant="warning"
          disabled={!isActive || busy}
          onClick={onUnlock}
          icon={
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="2" y="5" width="6" height="4" rx="0.5" />
              <path d="M3.5 5V3.5a1.5 1.5 0 013 0" />
            </svg>
          }
        >
          Unlock
        </Button>
      )}

      <Button
        variant="danger"
        disabled={!isActive || busy}
        onClick={onStop}
        icon={
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="2" width="6" height="6" rx="0.5" />
          </svg>
        }
      >
        Stop
      </Button>

      <Button
        variant="danger"
        disabled={!isActive || busy}
        onClick={handleKill}
        className={showKillConfirm ? "!bg-[#ff4444]/20 !border-[#ff4444]/30 animate-pulse" : ""}
        icon={
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="5" cy="5" r="4" />
            <line x1="3" y1="3" x2="7" y2="7" />
            <line x1="7" y1="3" x2="3" y2="7" />
          </svg>
        }
      >
        {showKillConfirm ? "Confirm" : "Kill"}
      </Button>

      <div className="w-px h-4 bg-[#1a1a1a] mx-0.5" />

      <Button
        variant="primary"
        disabled={!canInject || busy}
        onClick={onToggleInject}
        icon={
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M1 7c0-1.5 1-2 3-2s3 .5 3 2" />
            <path d="M7.5 1.5l1.5 3-3 3" />
          </svg>
        }
      >
        Inject
      </Button>

      {canResumeRun && (
        <>
          <div className="w-px h-4 bg-[#1a1a1a] mx-0.5" />
          <Button
            variant="success"
            disabled={busy}
            onClick={onResumeRun}
            icon={
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M1 5a4 4 0 017-2" />
                <polyline points="6 1 8 3 6 5" />
              </svg>
            }
          >
            Resume Run
          </Button>
        </>
      )}
    </div>
  );
}
