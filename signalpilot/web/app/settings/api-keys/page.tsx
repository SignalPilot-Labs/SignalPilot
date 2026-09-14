"use client";

import { useState } from "react";
import { Key, Plus, AlertTriangle } from "lucide-react";
import { useAppAuth } from "~/lib/auth-context";
import type { ApiKeyCreatedResponse } from "~/lib/backend-client";
import { useSubscription } from "~/lib/subscription-context";
import { PageHeader, TerminalBar } from "~/components/ui/page-header";
import { EmptyState, EmptyList } from "~/components/ui/empty-states";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { StatusDot } from "~/components/ui/data-viz";
import { SectionHeader } from "~/components/ui/section-header";
import { useToast } from "~/components/ui/toast";
import { ApiKeysSkeleton } from "~/components/ui/skeleton";
import { useApiKeys, invalidateApiKeys } from "~/lib/hooks/use-gateway-data";
import { PageLoader } from "~/components/ui/page-loader";
import { createApiKey, deleteApiKey } from "~/lib/api";
import { NewKeyReveal } from "./_components/new-key-reveal";
import { CreateKeyForm } from "./_components/create-key-form";
import { KeyRow, TableHeader } from "./_components/key-table";

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Gate component — renders before any Clerk hooks to avoid crash in local mode
// ---------------------------------------------------------------------------

export default function ApiKeysPage() {
  const { isCloudMode, isLoaded } = useAppAuth();

  if (!isLoaded) {
    return <ApiKeysSkeleton />;
  }

  if (isCloudMode) {
    return <ApiKeysContent />;
  }

  return <LocalApiKeysContent />;
}

// ---------------------------------------------------------------------------
// Content component — safe to call useBackendClient() (ClerkProvider is present)
// ---------------------------------------------------------------------------

function ApiKeysContent() {
  const { isLoaded } = useAppAuth();
  const { toast } = useToast();

  const { data: keys = [], isLoading, error: swrError } = useApiKeys();
  const { tier } = useSubscription();
  const loadError = swrError ? String(swrError) : null;
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newlyCreated, setNewlyCreated] = useState<ApiKeyCreatedResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Map of key_id -> total_requests, populated from real or mock data
  const [requestCounts, setRequestCounts] = useState<Map<string, number>>(new Map());

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (!isLoaded || isLoading) {
    return <PageLoader label="loading api keys" />;
  }

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  function handleCreated(created: ApiKeyCreatedResponse) {
    setNewlyCreated(created);
    setShowCreateForm(false);
    // New key starts with 0 requests
    setRequestCounts((prev) => new Map(prev).set(created.id, 0));
    invalidateApiKeys();
    toast("api key created", "success");
  }

  async function handleDelete(id: string) {
    setDeleting(true);
    try {
      await deleteApiKey(id);
      setRequestCounts((prev) => {
        const next = new Map(prev);
        next.delete(id);
        return next;
      });
      invalidateApiKeys();
      toast("api key deleted", "success");
    } catch (e) {
      toast("failed to delete key", "error");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-8 max-w-4xl animate-fade-in">
      <PageHeader
        title="api keys"
        subtitle="auth"
        description="manage programmatic access keys for the signalpilot backend"
      />

      <TerminalBar
        path="settings/api-keys --list"
        status={
          <StatusDot status={loadError ? "error" : "healthy"} size={4} />
        }
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            keys:{" "}
            <code className="text-[12px] text-[var(--color-text)]">{keys.length}</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            plan:{" "}
            <code className="text-[12px] text-[var(--color-text)]">{tier}</code>
          </span>
        </div>
      </TerminalBar>

      {/* Newly created key reveal */}
      {newlyCreated && (
        <div className="mb-6">
          <NewKeyReveal
            created={newlyCreated}
            onDismiss={() => setNewlyCreated(null)}
          />
        </div>
      )}

      {/* Keys section */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <SectionHeader icon={Key} title="active keys" />
          {!showCreateForm && (
            <button
              onClick={() => setShowCreateForm(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] rounded-[10px] transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Plus className="w-3 h-3" />
              create new key
            </button>
          )}
        </div>

        {/* Inline create form */}
        {showCreateForm && (
          <div className="mb-4">
            <CreateKeyForm
              createFn={(name, scopes) => createApiKey(name, scopes)}
              onCreated={handleCreated}
              onCancel={() => setShowCreateForm(false)}
            />
          </div>
        )}

        {/* Error banner */}
        {loadError && (
          <div className="mb-4 flex items-start gap-2 p-3 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 rounded-[10px] animate-fade-in">
            <AlertTriangle
              className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-error)]">
              {loadError}
            </p>
          </div>
        )}

        {/* Keys table or empty state */}
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] overflow-hidden">
          {keys.length === 0 ? (
            <EmptyState
              icon={EmptyList}
              title="no api keys"
              description="create a key to enable programmatic access to the signalpilot backend"
              action={
                !showCreateForm ? (
                  <button
                    onClick={() => setShowCreateForm(true)}
                    className="flex items-center gap-1.5 px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors duration-150"
                  >
                    <Plus className="w-3 h-3" />
                    create first key
                  </button>
                ) : undefined
              }
            />
          ) : (
            <>
              <TableHeader />
              {keys.map((key) => (
                <KeyRow
                  key={key.id}
                  apiKey={key}
                  requestCount={requestCounts.get(key.id) ?? 0}
                  onDelete={(id) => setDeleteTarget(id)}
                />
              ))}
            </>
          )}
        </div>
      </section>

      {/* Confirm delete dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="delete api key"
        message={`this will permanently revoke the key "${keys.find((k) => k.id === deleteTarget)?.name ?? ""}". any applications using it will immediately lose access.`}
        confirmLabel={deleting ? "deleting..." : "delete key"}
        cancelLabel="cancel"
        variant="danger"
        onConfirm={() => {
          if (deleteTarget) handleDelete(deleteTarget);
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Local mode content — uses gateway /api/keys endpoints directly
// ---------------------------------------------------------------------------

function LocalApiKeysContent() {
  const { toast } = useToast();

  const { data: keys = [], isLoading, error: swrError } = useApiKeys();
  const loadError = swrError ? String(swrError) : null;
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newlyCreated, setNewlyCreated] = useState<ApiKeyCreatedResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [requestCounts] = useState<Map<string, number>>(new Map());

  if (isLoading) {
    return <PageLoader label="loading api keys" />;
  }

  function handleCreated(created: ApiKeyCreatedResponse) {
    setNewlyCreated(created);
    setShowCreateForm(false);
    invalidateApiKeys();
    toast("api key created", "success");
  }

  async function handleDelete(id: string) {
    setDeleting(true);
    try {
      await deleteApiKey(id);
      invalidateApiKeys();
      toast("api key deleted", "success");
    } catch {
      toast("failed to delete key", "error");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  }

  return (
    <div className="p-8 max-w-4xl animate-fade-in">
      <PageHeader
        title="api keys"
        subtitle="local"
        description="manage gateway api keys for programmatic access"
      />

      <TerminalBar
        path="settings/api-keys --list"
        status={<StatusDot status={loadError ? "error" : "healthy"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            keys:{" "}
            <code className="text-[12px] text-[var(--color-text)]">{keys.length}</code>
          </span>
        </div>
      </TerminalBar>

      {newlyCreated && (
        <div className="mb-6">
          <NewKeyReveal created={newlyCreated} onDismiss={() => setNewlyCreated(null)} />
        </div>
      )}

      <section className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <SectionHeader icon={Key} title="active keys" />
          {!showCreateForm && (
            <button
              onClick={() => setShowCreateForm(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] rounded-[10px] transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Plus className="w-3 h-3" />
              create new key
            </button>
          )}
        </div>

        {showCreateForm && (
          <div className="mb-4">
            <CreateKeyForm
              createFn={(name, scopes) => createApiKey(name, scopes)}
              onCreated={handleCreated}
              onCancel={() => setShowCreateForm(false)}
            />
          </div>
        )}

        {loadError && (
          <div className="mb-4 flex items-start gap-2 p-3 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 rounded-[10px] animate-fade-in">
            <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
            <p className="text-[12px] text-[var(--color-error)]">{loadError}</p>
          </div>
        )}

        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] overflow-hidden">
          {keys.length === 0 ? (
            <EmptyState
              icon={EmptyList}
              title="no api keys"
              description="create a key to enable programmatic access to the signalpilot gateway"
              action={
                !showCreateForm ? (
                  <button
                    onClick={() => setShowCreateForm(true)}
                    className="flex items-center gap-1.5 px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors duration-150"
                  >
                    <Plus className="w-3 h-3" />
                    create first key
                  </button>
                ) : undefined
              }
            />
          ) : (
            <>
              <TableHeader />
              {keys.map((key) => (
                <KeyRow
                  key={key.id}
                  apiKey={key}
                  requestCount={requestCounts.get(key.id) ?? 0}
                  onDelete={(id) => setDeleteTarget(id)}
                />
              ))}
            </>
          )}
        </div>
      </section>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="delete api key"
        message={`this will permanently revoke the key "${keys.find((k) => k.id === deleteTarget)?.name ?? ""}". any applications using it will immediately lose access.`}
        confirmLabel={deleting ? "deleting..." : "delete key"}
        cancelLabel="cancel"
        variant="danger"
        onConfirm={() => { if (deleteTarget) handleDelete(deleteTarget); }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
