"use client";

import { useState, type FormEvent } from "react";
import { Loader2, Search } from "lucide-react";
import { discoverGitHubInstallations, requestErrorStatus } from "~/lib/api";
import type { GitHubInstallation } from "~/lib/types";

interface LinkExistingInstallationProps {
  /** Called after installations were linked so the caller can reload. */
  onLinked: (installations: GitHubInstallation[]) => void;
}

const CLAIMED_MESSAGE =
  "This GitHub installation is already connected to a different SignalPilot organization.";

function discoverErrorMessage(err: unknown): string {
  const status = requestErrorStatus(err);
  if (status === 403) return "Only organization admins can link installations";
  if (status === 409) return CLAIMED_MESSAGE;
  if (status === 404) {
    return "No installation of the SignalPilot GitHub App was found for that account";
  }
  const raw = err instanceof Error ? err.message : String(err);
  return raw || "Failed to link the installation";
}

/**
 * Lets an org admin attach a GitHub App installation that already exists
 * on GitHub (for example one made from the GitHub UI) to this org.
 */
export function LinkExistingInstallation({ onLinked }: LinkExistingInstallationProps) {
  const [open, setOpen] = useState(false);
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ kind: "success" | "error"; text: string } | null>(
    null,
  );

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const login = account.trim();
    if (!login || busy) return;
    setBusy(true);
    setResult(null);
    try {
      const linked = await discoverGitHubInstallations(login);
      const n = linked.length;
      setResult({
        kind: "success",
        text:
          n === 0
            ? `No new installations were linked for ${login}`
            : `Linked ${n} installation${n === 1 ? "" : "s"} for ${login}`,
      });
      setAccount("");
      onLinked(linked);
    } catch (err) {
      setResult({ kind: "error", text: discoverErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="px-5 py-3 border-t border-[var(--color-border)]">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150"
        >
          Already installed? <span className="underline">Link an existing installation</span>
        </button>
      ) : (
        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <span className="text-[11px] text-[var(--color-text-dim)]">
            enter the GitHub user or organization login where the SignalPilot app is installed
          </span>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              placeholder="github-org-login"
              autoFocus
              disabled={busy}
              className="flex-1 max-w-xs px-3 py-1.5 text-xs font-mono text-[var(--color-text)] bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] focus:outline-none focus:border-[var(--color-text-dim)] disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={busy || !account.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--color-text)] bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-text-dim)] transition-colors duration-150 disabled:opacity-50"
            >
              {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
              link installation
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setResult(null);
              }}
              disabled={busy}
              className="px-3 py-1.5 text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors duration-150"
            >
              cancel
            </button>
          </div>
          {result && (
            <p
              role={result.kind === "error" ? "alert" : "status"}
              className={`text-[11px] ${
                result.kind === "error"
                  ? "text-[var(--color-error)]"
                  : "text-[var(--color-text)]"
              }`}
            >
              {result.text}
            </p>
          )}
        </form>
      )}
    </div>
  );
}
