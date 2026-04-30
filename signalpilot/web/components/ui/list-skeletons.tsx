import React from "react";

/**
 * List-shaped shimmer skeletons for async lists:
 * - TeamMemberListSkeleton  (members section first paint)
 * - InvitationListSkeleton  (invitations section first paint)
 * - SessionListSkeleton     (active sessions section first paint)
 *
 * aria-busy and the sr-only span are omitted here — the parent container
 * already owns aria-live="polite" and aria-busy={loading}. Adding them
 * inside would cause duplicate SR announcements.
 *
 * Line budget: < 130 lines.
 */

import { Skeleton } from "./skeleton";

export function TeamMemberListSkeleton({ rows = 3 }: { rows?: number }): React.JSX.Element {
  return (
    <div className="divide-y divide-[var(--color-border)]">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 py-2.5 px-4">
          {/* Avatar circle */}
          <Skeleton className="w-7 h-7 rounded-full flex-shrink-0" />
          {/* Name + email */}
          <div className="flex-1 min-w-0 space-y-1.5">
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-2 w-44" />
          </div>
          {/* Role pill */}
          <Skeleton className="h-5 w-16 flex-shrink-0" />
          {/* Remove button */}
          <Skeleton className="h-7 w-12 flex-shrink-0" />
        </div>
      ))}
    </div>
  );
}

export function InvitationListSkeleton({ rows = 3 }: { rows?: number }): React.JSX.Element {
  return (
    <div className="divide-y divide-[var(--color-border)]">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 py-2.5 px-4">
          {/* Envelope icon block */}
          <Skeleton className="w-3.5 h-3.5 flex-shrink-0" />
          {/* Email */}
          <Skeleton className="flex-1 h-3 w-48" />
          {/* Role pill */}
          <Skeleton className="h-5 w-16 flex-shrink-0" />
          {/* Invited-at text */}
          <Skeleton className="h-2 w-20 flex-shrink-0" />
          {/* Revoke button */}
          <Skeleton className="h-7 w-12 flex-shrink-0" />
        </div>
      ))}
    </div>
  );
}

export function SessionListSkeleton({ rows = 3 }: { rows?: number }): React.JSX.Element {
  return (
    <div className="divide-y divide-[var(--color-border)]">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 py-3 px-4">
          {/* Device icon */}
          <Skeleton className="w-4 h-4 flex-shrink-0" />
          {/* Browser + meta */}
          <div className="flex-1 min-w-0 space-y-1.5">
            <Skeleton className="h-3 w-44" />
            <Skeleton className="h-2 w-32" />
          </div>
          {/* Revoke button */}
          <Skeleton className="h-7 w-12 flex-shrink-0" />
        </div>
      ))}
    </div>
  );
}
