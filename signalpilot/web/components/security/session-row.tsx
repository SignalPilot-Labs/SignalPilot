"use client";

/**
 * Single session row: device icon, device info, location, last-active.
 * Current session: neutral "this device" pill.
 * Other sessions: revoke button.
 */

import { Monitor, Smartphone } from "lucide-react";
import type { SessionWithActivitiesResource } from "@clerk/types";
import { formatDevice, formatLocation, formatLastActive } from "@/lib/sessions/format-session";
import { NEUTRAL_CLASS } from "@/components/auth/auth-primitives";

export interface SessionRowProps {
  session: SessionWithActivitiesResource;
  isCurrent: boolean;
  onRevoke?: (session: SessionWithActivitiesResource) => void;
}

export function SessionRow({ session, isCurrent, onRevoke }: SessionRowProps) {
  const act = session.latestActivity;
  const DeviceIcon = act.isMobile ? Smartphone : Monitor;

  return (
    <div className="flex items-center gap-3 py-3 px-4">
      {/* Device icon */}
      <DeviceIcon
        className="w-4 h-4 text-[var(--color-text-dim)] flex-shrink-0"
        strokeWidth={1.5}
      />

      {/* Device + location info */}
      <div className="flex-1 min-w-0">
        <p className="text-[13px] text-[var(--color-text)] font-mono truncate">
          {formatDevice(act)}
        </p>
        <p className={`${NEUTRAL_CLASS} truncate`}>
          {formatLocation(act)} · {formatLastActive(session.lastActiveAt)}
        </p>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {isCurrent ? (
          <span className="px-2 py-0.5 text-[11px] font-mono tracking-wider border border-[var(--color-border)] text-[var(--color-text-dim)]">
            this device
          </span>
        ) : (
          onRevoke && (
            <button
              type="button"
              onClick={() => onRevoke(session)}
              aria-label={`revoke session on ${formatDevice(act)}`}
              className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-error)] tracking-wider font-mono transition-colors focus:outline-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-text)]"
            >
              revoke
            </button>
          )
        )}
      </div>
    </div>
  );
}
