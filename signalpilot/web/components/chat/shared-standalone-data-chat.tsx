"use client";

import {
  AlertCircle,
  ArrowLeft,
  GitFork,
  Loader2,
  LockKeyhole,
  Sparkles,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import useSWR from "swr";
import { ArtifactPreview } from "~/components/chat/standalone-data-chat";
import { useToast } from "~/components/ui/toast";
import {
  downloadSharedStandaloneArtifact,
  forkSharedStandaloneConversation,
  getSharedStandaloneForkPreview,
  getSharedStandaloneConversation,
  type StandaloneForkPreview,
} from "~/lib/api";

export function SharedStandaloneDataChat({ token }: { token: string }) {
  const router = useRouter();
  const { toast } = useToast();
  const [forking, setForking] = useState(false);
  const [forkPreview, setForkPreview] = useState<StandaloneForkPreview | null>(
    null,
  );
  const [perQueryBudget, setPerQueryBudget] = useState(0.25);
  const [chatBudget, setChatBudget] = useState(1);
  const { data, error, isLoading } = useSWR(
    `shared-standalone-chat:${token}`,
    () => getSharedStandaloneConversation(token),
    { revalidateOnFocus: false },
  );
  const messageIds = useMemo(
    () => new Set(data?.messages.map((message) => message.id) ?? []),
    [data?.messages],
  );
  const unattachedArtifacts =
    data?.artifacts.filter(
      (artifact) =>
        !artifact.assistant_message_id ||
        !messageIds.has(artifact.assistant_message_id),
    ) ?? [];
  const downloadArtifact = useCallback(
    (artifactId: string, format: string, filename: string) =>
      downloadSharedStandaloneArtifact(token, artifactId, format, filename),
    [token],
  );

  const prepareFork = async () => {
    setForking(true);
    try {
      const preview = await getSharedStandaloneForkPreview(token);
      setForkPreview(preview);
      setPerQueryBudget(preview.per_query_budget_usd);
      setChatBudget(preview.chat_budget_usd);
    } catch (forkError) {
      toast(
        forkError instanceof Error
          ? forkError.message
          : "Could not fork this conversation",
        "error",
      );
    } finally {
      setForking(false);
    }
  };

  const confirmFork = async () => {
    setForking(true);
    try {
      const fork = await forkSharedStandaloneConversation(
        token,
        perQueryBudget,
        chatBudget,
      );
      router.push(`/chats/${fork.id}`);
    } catch (forkError) {
      toast(
        forkError instanceof Error
          ? forkError.message
          : "Could not fork this conversation",
        "error",
      );
      setForking(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-screen items-center justify-center p-8">
        <div className="max-w-md rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-6 text-center">
          <AlertCircle className="mx-auto h-5 w-5 text-[var(--color-text-dim)]" />
          <h1 className="mt-3 text-base text-[var(--color-text)]">
            Shared conversation unavailable
          </h1>
          <p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">
            This link is invalid, revoked, archived, or belongs to another
            organization.
          </p>
          <button
            type="button"
            onClick={() => router.push("/chats")}
            className="mt-4 rounded-lg border border-[var(--color-border)] px-3 py-2 text-xs text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]"
          >
            Go to your chats
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen min-w-[720px] overflow-hidden p-4">
      <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg)] shadow-2xl shadow-black/20">
        <header className="flex h-16 flex-none items-center justify-between border-b border-[var(--color-border)] px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              aria-label="Back to your chats"
              onClick={() => router.push("/chats")}
              className="rounded-lg p-2 text-[var(--color-text-dim)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.15em] text-[var(--color-text-dim)]">
                <LockKeyhole className="h-3 w-3" />
                Team-shared chat
              </div>
              <div className="max-w-xl truncate text-sm text-[var(--color-text)]">
                {data.conversation.title}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {data.conversation.project_name && (
              <span className="text-xs text-[var(--color-text-dim)]">
                {data.conversation.project_name}
              </span>
            )}
            <span className="rounded-full border border-[var(--color-border)] px-2.5 py-1 text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-dim)]">
              Read only
            </span>
            <button
              type="button"
              disabled={forking}
              onClick={() => void prepareFork()}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {forking ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <GitFork className="h-3.5 w-3.5" />
              )}
              Fork to my chats
            </button>
          </div>
        </header>

        {forkPreview && (
          <section
            role="dialog"
            aria-label="Confirm chat fork"
            className="border-b border-[var(--color-border)] bg-[var(--color-bg-card)] px-6 py-4"
          >
            <div className="mx-auto max-w-3xl text-xs text-[var(--color-text-muted)]">
              <div className="font-medium text-[var(--color-text)]">
                Confirm a private fork of {forkPreview.project_name}
              </div>
              <div className="mt-1 font-mono text-[10px]">
                Frozen commit {forkPreview.commit_sha}
              </div>
              <p className="mt-2">{forkPreview.warehouse_cost_notice}</p>
              <div className="mt-3 flex items-end gap-3">
                <label>
                  <span className="block pb-1">Per-query budget (USD)</span>
                  <input
                    aria-label="Fork per-query budget in USD"
                    type="number"
                    min="0"
                    step="0.01"
                    value={perQueryBudget}
                    onChange={(event) =>
                      setPerQueryBudget(Number(event.target.value))
                    }
                    className="w-32 rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1.5"
                  />
                </label>
                <label>
                  <span className="block pb-1">Chat budget (USD)</span>
                  <input
                    aria-label="Fork cumulative chat budget in USD"
                    type="number"
                    min="0"
                    step="0.01"
                    value={chatBudget}
                    onChange={(event) =>
                      setChatBudget(Number(event.target.value))
                    }
                    className="w-32 rounded border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1.5"
                  />
                </label>
                <button
                  type="button"
                  disabled={forking || chatBudget < perQueryBudget}
                  onClick={() => void confirmFork()}
                  className="rounded bg-[var(--color-text)] px-3 py-2 text-[var(--color-bg)] disabled:opacity-50"
                >
                  Confirm and create fork
                </button>
                <button
                  type="button"
                  onClick={() => setForkPreview(null)}
                  className="rounded border border-[var(--color-border)] px-3 py-2"
                >
                  Cancel
                </button>
              </div>
            </div>
          </section>
        )}

        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-6 py-6">
            <div className="mb-6 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] px-4 py-3 text-xs leading-5 text-[var(--color-text-muted)]">
              This authenticated view includes the business conversation and
              completed artifacts. SQL, tool traces, and work details are not
              shared. Fork it to continue privately in your own chat.
            </div>

            <div className="space-y-2">
              {data.messages.map((message) =>
                message.role === "user" ? (
                  <div
                    key={message.id}
                    className="ml-auto max-w-[78%] rounded-2xl rounded-br-md border border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-4 py-3 text-sm leading-6 text-[var(--color-text)]"
                  >
                    <div className="whitespace-pre-wrap">{message.content}</div>
                  </div>
                ) : (
                  <div key={message.id} className="flex gap-3 py-5">
                    <div className="mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)]">
                      <Sparkles className="h-3.5 w-3.5 text-[var(--color-text-muted)]" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="chat-markdown">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content}
                        </ReactMarkdown>
                      </div>
                      <div className="mt-5 space-y-4">
                        {data.artifacts
                          .filter(
                            (artifact) =>
                              artifact.assistant_message_id === message.id,
                          )
                          .map((artifact) => (
                            <ArtifactPreview
                              key={artifact.id}
                              artifact={artifact}
                              onDownload={downloadArtifact}
                            />
                          ))}
                      </div>
                    </div>
                  </div>
                ),
              )}
            </div>

            {unattachedArtifacts.length > 0 && (
              <section className="mt-8 border-t border-[var(--color-border)] pt-6">
                <h2 className="mb-4 text-xs uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
                  Completed artifacts
                </h2>
                <div className="space-y-4">
                  {unattachedArtifacts.map((artifact) => (
                    <ArtifactPreview
                      key={artifact.id}
                      artifact={artifact}
                      onDownload={downloadArtifact}
                    />
                  ))}
                </div>
              </section>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
