"use client";

import { UserButton } from "@clerk/nextjs";

export default function ClerkUserButton({
  displayName,
}: {
  displayName: string;
}) {
  return (
    <div className="flex items-center gap-2 px-1 py-1">
      <UserButton
        appearance={{
          elements: {
            userButtonAvatarBox: {
              width: "24px",
              height: "24px",
              borderRadius: "0px",
            },
            userButtonPopoverCard: {
              borderRadius: "0px",
              backgroundColor: "#0a0a0a",
              border: "1px solid #222222",
            },
          },
        }}
      />
      <span
        className="text-[11px] text-[var(--color-text-dim)] tracking-wide truncate max-w-[120px]"
        title={displayName}
      >
        {displayName}
      </span>
    </div>
  );
}
