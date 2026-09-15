"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { ReadOnlyNote } from "~/components/access/read-only-note";
import { usePermissions } from "~/lib/hooks/use-permissions";

/**
 * The "connect notion" / "connect slack" install button on the integrations
 * page. Installing an integration is an org-level change (`integrations.write`),
 * so a member never sees the button: the header slot renders nothing and the
 * empty-state slot renders the read-only note instead.
 */
export function IntegrationConnectButton({
  label,
  icon,
  onConnect,
  connecting,
  variant = "header",
}: {
  label: string;
  icon: ReactNode;
  onConnect: () => void;
  connecting: boolean;
  variant?: "header" | "empty";
}) {
  const { can } = usePermissions();
  if (!can("integrations.write")) {
    if (variant === "header") return null;
    return <ReadOnlyNote>{label.replace(/^connect /, "")} is installed by an org admin</ReadOnlyNote>;
  }
  const className =
    variant === "header"
      ? "flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-bg)] bg-[var(--color-text)] rounded-[10px] hover:opacity-90 transition-opacity duration-150 disabled:opacity-30"
      : "inline-flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-[12px] rounded-[10px] transition-opacity duration-150 hover:opacity-90 disabled:opacity-30";
  return (
    <button onClick={onConnect} disabled={connecting} className={className} data-testid="integration-connect">
      {connecting ? <Loader2 className="w-3 h-3 animate-spin" /> : icon}
      {label}
    </button>
  );
}
