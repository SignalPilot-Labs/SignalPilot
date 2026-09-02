"use client";

// Inline artifact cards for the standalone data chat transcript.
//
// One card per file path per run, derived from run events joined to the
// gateway's file manifest (lib/chat-artifact-cards.ts). The card is an
// index with honest previews: only images render inline; every other kind
// routes to the artifacts panel, which is the reader.

import { AlertCircle, ArrowDownToLine } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import { downloadConversationFile } from "~/lib/api";
import {
  cardKindLabel,
  middleTruncate,
  primaryActionLabel,
  relativeTimeLabel,
  type ArtifactCardModel,
} from "~/lib/chat-artifact-cards";
import { formatByteSize } from "~/lib/chat-artifacts";
import { kindIcon } from "~/components/chat/artifacts-panel";
import { useChatUi } from "~/components/chat/chat-ui-context";
import { useFileObjectUrl } from "~/components/chat/use-file-object-url";
import { useToast } from "~/components/ui/toast";

/** Full cards rendered before the block collapses to compact rows. */
const MAX_FULL_CARDS = 3;

/**
 * Invisible overlay that stretches the primary button's hit area over the
 * whole card (the card container must be `relative`; the button itself
 * stays unpositioned so the overlay resolves against the card). One tab
 * stop, a real <button>, the shared button:focus-visible mint outline for
 * free — and no role="button" wrappers around other buttons.
 *
 * The host button MUST include STRETCHED_HOST: the global press effect
 * (globals.css `button:active { transform: scale(0.98) }`) would otherwise
 * turn the pressed button into a containing block mid-click, collapsing
 * the overlay between mousedown and mouseup and dropping the click.
 */
function StretchedHitArea() {
  return <span aria-hidden="true" className="absolute inset-0 cursor-pointer" />;
}

/** Required classes on a button hosting StretchedHitArea. */
const STRETCHED_HOST = "cursor-pointer active:transform-none!";

/** Expand a small icon button's hit area to ~44px without growing it. */
const EXPANDED_HIT = "after:absolute after:content-['']";

type CardActionsProps = {
  card: ArtifactCardModel;
  conversationId: string | null;
  onOpen: (fileId: string) => void;
};

function useDownload(conversationId: string | null) {
  const { toast } = useToast();
  return async (card: ArtifactCardModel) => {
    if (!conversationId || !card.file) return;
    try {
      await downloadConversationFile(
        conversationId,
        card.file.id,
        card.filename,
      );
    } catch {
      toast("This file is no longer available.", "error");
    }
  };
}

/**
 * Inline thumbnail for image cards. Fetches through the shared object-URL
 * cache (plain <a href> cannot carry auth), so the inline figure, the panel
 * viewer and this thumbnail share one fetch per file version; a new
 * content hash refetches so an updated chart never shows stale pixels. The
 * fixture harness has no gateway, so it injects `getFileObjectUrl` via the
 * chat UI context — the thumbnail path stays verifiable at /chats/test.
 */
function ImageThumb({
  conversationId,
  card,
  onOpen,
}: {
  conversationId: string;
  card: ArtifactCardModel;
  onOpen: (fileId: string) => void;
}) {
  const { url, error } = useFileObjectUrl(card.file, conversationId);
  const fileId = card.file?.id;
  useEffect(() => {
    // Deliberate downgrade to the icon-only card — but never silently:
    // a broken thumbnail path in production must stay observable.
    if (error) {
      console.warn("chat-artifact-card: thumbnail fetch failed", card.path, error);
    }
  }, [error, card.path]);
  if (!url || !fileId) return null;
  return (
    <button
      type="button"
      data-testid="chat-artifact-card-thumb"
      aria-label={`Open ${card.filename}`}
      onClick={() => onOpen(fileId)}
      className="relative block w-full border-t border-[var(--color-border)] bg-[var(--color-bg-input)] p-3"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={card.filename}
        className="mx-auto max-h-[240px] max-w-full rounded-md"
      />
    </button>
  );
}

/** Kind icon inside a tinted well — the card's visual anchor. */
function IconWell({ kind }: { kind: string }) {
  return (
    <span className="flex h-10 w-10 flex-none items-center justify-center rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-elevated)] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      {kindIcon(kind, "h-5 w-5 flex-none text-[var(--color-text-muted)]")}
    </span>
  );
}

/**
 * The clock behind the relative timestamps. The fixture harness injects a
 * frozen `nowMs` through the chat UI context; live pages tick every 30s so
 * "just now" never lies overnight.
 */
function useCardNow(): number {
  const { nowMs } = useChatUi();
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    if (nowMs !== undefined) return;
    const interval = window.setInterval(() => setTick(Date.now()), 30_000);
    return () => window.clearInterval(interval);
  }, [nowMs]);
  return nowMs ?? tick;
}

function UpdatedBadge() {
  return (
    <span
      data-testid="chat-artifact-card-updated"
      className="flex-none rounded-full border border-[var(--color-success)]/25 bg-[var(--color-success)]/5 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] text-[var(--color-success)]"
    >
      Updated
    </span>
  );
}

/** Flash the card border once when its content hash changes in place. */
function useUpdateFlash(contentHash: string | undefined): boolean {
  const [flash, setFlash] = useState(false);
  const previous = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (previous.current !== undefined && previous.current !== contentHash) {
      setFlash(true);
      const timer = window.setTimeout(() => setFlash(false), 1_100);
      return () => window.clearTimeout(timer);
    }
    previous.current = contentHash;
  }, [contentHash]);
  return flash;
}

const FullCard = memo(function FullCard({
  card,
  conversationId,
  onOpen,
}: CardActionsProps) {
  const download = useDownload(conversationId);
  const flash = useUpdateFlash(card.file?.content_hash);
  const now = useCardNow();
  if (card.state === "unfinished") return <UnfinishedStub card={card} />;
  if (card.state === "pending" || !card.file) return <PendingCard card={card} />;
  const file = card.file;
  const label = cardKindLabel(card.kind, card.filename);
  const action = primaryActionLabel(card.kind);
  return (
    <section
      data-testid="chat-artifact-card"
      className={`chat-step-in group relative cursor-pointer overflow-hidden rounded-[var(--radius-card)] border bg-[var(--color-bg-card)] shadow-[0_1px_0_rgba(255,255,255,0.03)_inset] transition-colors hover:border-[var(--color-border-hover)] ${
        flash
          ? "chat-artifact-flash border-[var(--color-success)]/40"
          : "border-[var(--color-border)]"
      }`}
    >
      <div className="flex items-center gap-3.5 px-4 py-3.5">
        <IconWell kind={card.kind} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
              {label}
            </span>
            {card.updated && <UpdatedBadge />}
          </div>
          <p
            title={card.path}
            className="mt-0.5 truncate font-mono text-[12.5px] leading-5 text-[var(--color-text)]"
          >
            {middleTruncate(card.filename)}
          </p>
          <p className="mt-0.5 text-[11px] text-[var(--color-text-dim)]">
            {formatByteSize(file.byte_size)}
            <span className="px-1.5 text-[var(--color-text-dim)] opacity-50">
              ·
            </span>
            {relativeTimeLabel(file.updated_at, now)}
          </p>
        </div>
        <div className="flex flex-none items-center gap-1.5">
          {/* The stretched hit area makes the whole card this button's
              target: one tab stop, real semantics, mint focus ring. */}
          <button
            type="button"
            data-testid="chat-artifact-card-primary"
            aria-label={`${action} ${card.filename}`}
            onClick={() => onOpen(file.id)}
            className={`${STRETCHED_HOST} rounded-[var(--radius-ctl)] border border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-3.5 py-2 text-xs font-medium text-[var(--color-text)] transition-colors hover:border-[var(--color-border-hover)] hover:bg-[var(--color-bg-hover)]`}
          >
            {action}
            <StretchedHitArea />
          </button>
          <button
            type="button"
            data-testid="chat-artifact-card-download"
            aria-label={`Download ${card.filename}`}
            title="Download"
            onClick={() => void download(card)}
            className={`${EXPANDED_HIT} after:-inset-[5px] relative flex h-[34px] w-[34px] items-center justify-center rounded-[var(--radius-ctl)] text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text)]`}
          >
            <ArrowDownToLine className="h-4 w-4" />
          </button>
        </div>
      </div>
      {card.kind === "image" && conversationId && (
        <ImageThumb
          conversationId={conversationId}
          card={card}
          onOpen={onOpen}
        />
      )}
    </section>
  );
});

/** A write the mirror hasn't confirmed yet: resolves in place. The skeleton
 * sits where the size/time meta will appear, so it explains what is being
 * awaited; under reduced motion the shimmer freezes but the copy and
 * `aria-busy` still carry the meaning. */
function PendingCard({ card }: { card: ArtifactCardModel }) {
  return (
    <section
      data-testid="chat-artifact-card-pending"
      aria-busy="true"
      className="chat-step-in overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]"
    >
      <div className="flex items-center gap-3.5 px-4 py-3.5">
        <IconWell kind={card.kind} />
        <div className="min-w-0 flex-1">
          <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
            {cardKindLabel(card.kind, card.filename)}
          </span>
          <p
            title={card.path}
            className="mt-0.5 truncate font-mono text-[12.5px] leading-5 text-[var(--color-text-muted)]"
          >
            {middleTruncate(card.filename)}
          </p>
          <p className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--color-text-dim)]">
            <span
              aria-hidden="true"
              className="animate-shimmer h-2.5 w-14 flex-none rounded-full"
            />
            Still being written
          </p>
        </div>
      </div>
    </section>
  );
}

/** The run ended and the file never materialized — a quiet one-line stub,
 * never an orphaned shimmering card. */
function UnfinishedStub({ card }: { card: ArtifactCardModel }) {
  return (
    <p
      data-testid="chat-artifact-card-stub"
      className="flex items-center gap-2 px-1 text-[11.5px] text-[var(--color-text-dim)]"
    >
      <AlertCircle className="h-3.5 w-3.5 flex-none" />
      <span className="min-w-0 truncate">
        <span className="font-mono">{middleTruncate(card.filename)}</span>
        {" didn't finish"}
      </span>
    </p>
  );
}

/** Slim row used once a run block produces enough files to collapse. The
 * whole-row click is the stretched primary button — no role="button"
 * wrapper around real buttons (ARIA forbids interactive descendants). */
function CompactRow({ card, conversationId, onOpen }: CardActionsProps) {
  const download = useDownload(conversationId);
  if (card.state === "unfinished") return <UnfinishedStub card={card} />;
  const file = card.file;
  return (
    <div
      data-testid="chat-artifact-card-row"
      aria-busy={file ? undefined : true}
      className={`relative flex min-h-11 items-center gap-2.5 px-3 py-2 text-xs ${
        file ? "transition-colors hover:bg-[var(--color-bg-hover)]" : ""
      }`}
    >
      {kindIcon(card.kind)}
      <span
        title={card.path}
        className="min-w-0 truncate font-mono text-[11.5px] text-[var(--color-text)]"
      >
        {middleTruncate(card.filename, 52)}
      </span>
      {card.updated && <UpdatedBadge />}
      {file ? (
        <span className="ml-auto flex flex-none items-center gap-1">
          <span className="text-[10px] text-[var(--color-text-dim)]">
            {formatByteSize(file.byte_size)}
          </span>
          <button
            type="button"
            data-testid="chat-artifact-card-primary"
            aria-label={`${primaryActionLabel(card.kind)} ${card.filename}`}
            onClick={() => onOpen(file.id)}
            className={`${STRETCHED_HOST} rounded-md px-2 py-1 text-[11px] font-medium text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-text)]`}
          >
            {primaryActionLabel(card.kind)}
            <StretchedHitArea />
          </button>
          <button
            type="button"
            data-testid="chat-artifact-card-download"
            aria-label={`Download ${card.filename}`}
            title="Download"
            onClick={() => void download(card)}
            className={`${EXPANDED_HIT} after:-inset-2 relative flex h-7 w-7 items-center justify-center rounded-md text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-text)]`}
          >
            <ArrowDownToLine className="h-3.5 w-3.5" />
          </button>
        </span>
      ) : (
        <span className="ml-auto text-[10px] text-[var(--color-text-dim)]">
          Still being written
        </span>
      )}
    </div>
  );
}

/**
 * The card block for one run: up to three full cards, then a compact list
 * so a many-file run stays scannable.
 */
export function ChatArtifactCards({
  cards,
  conversationId,
  onOpen,
}: {
  cards: ArtifactCardModel[];
  conversationId: string | null;
  onOpen: (fileId: string) => void;
}) {
  if (cards.length === 0) return null;
  // Collapse only when at least two cards overflow: hiding a single file
  // behind a grouped header spends more space than it saves.
  const collapse = cards.length > MAX_FULL_CARDS + 1;
  const full = collapse ? cards.slice(0, MAX_FULL_CARDS) : cards;
  const rest = collapse ? cards.slice(MAX_FULL_CARDS) : [];
  return (
    <div data-testid="chat-artifact-cards" className="space-y-2.5">
      {full.map((card) => (
        <FullCard
          key={card.key}
          card={card}
          conversationId={conversationId}
          onOpen={onOpen}
        />
      ))}
      {rest.length > 0 && (
        <div className="chat-step-in overflow-hidden rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="border-b border-[var(--color-border)] bg-[var(--color-bg-elevated)] px-3 py-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--color-text-dim)]">
            {rest.length} more {rest.length === 1 ? "file" : "files"}
          </div>
          <div className="divide-y divide-[var(--color-border)]">
            {rest.map((card) => (
              <CompactRow
                key={card.key}
                card={card}
                conversationId={conversationId}
                onOpen={onOpen}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
