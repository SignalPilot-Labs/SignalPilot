"use client";

import { useState } from "react";
import {
  Key,
  Plus,
  Trash2,
  Loader2,
  Info,
  AlertTriangle,
} from "lucide-react";
import { useAppAuth } from "@/lib/auth-context";
import type { ApiKeyResponse, ApiKeyCreatedResponse } from "@/lib/backend-client";
import { useSubscription } from "@/lib/subscription-context";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { EmptyState, EmptyList } from "@/components/ui/empty-states";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { StatusDot } from "@/components/ui/data-viz";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { ApiKeysSkeleton } from "@/components/ui/skeleton";
import { CopyButton } from "@/components/ui/copy-button";
import { ALL_SCOPES } from "@/lib/api-key-scopes";
import { useApiKeys, invalidateApiKeys, usePlan } from "@/lib/hooks/use-gateway-data";
import { PageLoader } from "@/components/ui/page-loader";
import {
  createApiKey,
  deleteApiKey,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// New key revealed panel
// ---------------------------------------------------------------------------

function NewKeyReveal({
  created,
  onDismiss,
}: {
  created: ApiKeyCreatedResponse;
  onDismiss: () => void;
}) {
  const mcpUrl = `${process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300"}/mcp`;
  const mcpConfig = JSON.stringify({
    mcpServers: {
      signalpilot: {
        type: "http",
        url: mcpUrl,
        headers: { "X-API-Key": created.raw_key },
      },
    },
  }, null, 2);

  return (
    <div className="border border-[var(--color-success)]/30 bg-[var(--color-success)]/5 p-5 animate-fade-in">
      {/* Warning banner */}
      <div className="flex items-start gap-2 mb-4">
        <AlertTriangle
          className="w-3.5 h-3.5 text-[var(--color-warning)] mt-0.5 flex-shrink-0"
          strokeWidth={1.5}
        />
        <p className="text-[12px] text-[var(--color-warning)] tracking-wider leading-relaxed">
          copy this key now. it will not be shown again.
        </p>
      </div>

      {/* Key display */}
      <div className="flex items-center gap-3 mb-4">
        <code className="flex-1 px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] text-[var(--color-success)] tracking-wider break-all font-mono">
          {created.raw_key}
        </code>
        <CopyButton text={created.raw_key} />
      </div>

      {/* Key metadata */}
      <div className="flex items-center gap-6 text-[11px] text-[var(--color-text-dim)] tracking-wider mb-4">
        <span>
          name: <span className="text-[var(--color-text-muted)]">{created.name}</span>
        </span>
        <span>
          prefix: <code className="text-[var(--color-text-muted)]">{created.prefix}</code>
        </span>
        <span>
          scopes:{" "}
          <span className="text-[var(--color-text-muted)]">{created.scopes.join(", ")}</span>
        </span>
      </div>

      {/* MCP connection config */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider">mcp connection config</span>
          <CopyButton text={mcpConfig} />
        </div>
        <pre className="px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[11px] text-[var(--color-text-muted)] tracking-wider font-mono overflow-x-auto whitespace-pre">
{mcpConfig}
        </pre>
        <p className="text-[10px] text-[var(--color-text-dim)] mt-1 tracking-wider opacity-60">
          paste into .mcp.json (Claude Code) or .cursor/mcp.json (Cursor)
        </p>
      </div>

      <button
        onClick={onDismiss}
        className="text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider uppercase"
      >
        i&apos;ve copied it, dismiss
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create key form (inline)
// ---------------------------------------------------------------------------

function CreateKeyForm({
  onCreated,
  onCancel,
  createFn,
}: {
  onCreated: (key: ApiKeyCreatedResponse) => void;
  onCancel: () => void;
  createFn: (name: string, scopes: string[]) => Promise<ApiKeyCreatedResponse>;
}) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read", "query"]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleScope(scope: string) {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  }

  async function handleCreate() {
    if (!name.trim()) {
      setError("key name is required");
      return;
    }
    if (scopes.length === 0) {
      setError("select at least one scope");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await createFn(name.trim(), scopes);
      onCreated(created);
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 animate-fade-in">
      <div className="space-y-4">
        {/* Name input */}
        <div>
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">
            key name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
              if (e.key === "Escape") onCancel();
            }}
            placeholder="e.g. production, ci-pipeline, local-dev"
            autoFocus
            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
          />
        </div>

        {/* Scopes */}
        <div>
          <label className="block text-[12px] text-[var(--color-text-dim)] mb-2 tracking-wider">
            scopes
          </label>
          <div className="grid grid-cols-2 gap-2">
            {ALL_SCOPES.map((s) => {
              const checked = scopes.includes(s.value);
              return (
                <label
                  key={s.value}
                  className={`flex items-start gap-2.5 px-3 py-2.5 border cursor-pointer transition-all ${
                    checked
                      ? "border-[var(--color-success)]/40 bg-[var(--color-success)]/5"
                      : "border-[var(--color-border)] hover:border-[var(--color-border-hover)]"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleScope(s.value)}
                    className="mt-0.5 accent-[var(--color-success)]"
                  />
                  <div>
                    <span className="text-[12px] text-[var(--color-text-muted)] tracking-wider">
                      {s.label}
                    </span>
                    <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider mt-0.5">
                      {s.description}
                    </p>
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        {/* Error */}
        {error && (
          <p className="text-[12px] text-[var(--color-error)] tracking-wider">{error}</p>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={handleCreate}
            disabled={creating || !name.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30"
          >
            {creating ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Key className="w-3 h-3" />
            )}
            create key
          </button>
          <button
            onClick={onCancel}
            disabled={creating}
            className="px-4 py-2 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider uppercase"
          >
            cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Keys table row
// ---------------------------------------------------------------------------

function KeyRow({
  apiKey,
  requestCount,
  onDelete,
}: {
  apiKey: ApiKeyResponse;
  requestCount: number;
  onDelete: (id: string) => void;
}) {
  const createdDate = new Date(apiKey.created_at).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  const lastUsed = apiKey.last_used_at
    ? new Date(apiKey.last_used_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "never";

  return (
    <div className="flex items-center gap-4 px-5 py-3 border-b border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors group">
      {/* Name */}
      <div className="flex-1 min-w-0">
        <span className="text-xs text-[var(--color-text-muted)] tracking-wider">
          {apiKey.name}
        </span>
      </div>

      {/* Prefix */}
      <code className="text-[12px] text-[var(--color-text-dim)] tracking-wider w-28 flex-shrink-0">
        {apiKey.prefix}...
      </code>

      {/* Scopes */}
      <div className="flex items-center gap-1.5 w-44 flex-shrink-0 flex-wrap">
        {apiKey.scopes.map((scope) => (
          <span
            key={scope}
            className="px-1.5 py-0.5 text-[11px] border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider"
          >
            {scope}
          </span>
        ))}
      </div>

      {/* Created */}
      <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider w-28 flex-shrink-0 tabular-nums">
        {createdDate}
      </span>

      {/* Last used */}
      <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider w-24 flex-shrink-0 tabular-nums">
        {lastUsed}
      </span>

      {/* Requests */}
      <span className="text-[12px] text-[var(--color-text-dim)] tracking-wider w-20 flex-shrink-0 tabular-nums">
        {requestCount.toLocaleString()}
      </span>

      {/* Delete */}
      <button
        onClick={() => onDelete(apiKey.id)}
        aria-label={`delete api key ${apiKey.name}`}
        className="opacity-0 group-hover:opacity-100 flex items-center gap-1 px-2 py-1 text-[12px] text-[var(--color-error)] border border-[var(--color-error)]/20 hover:bg-[var(--color-error)]/5 hover:border-[var(--color-error)]/40 transition-all tracking-wider uppercase"
      >
        <Trash2 className="w-3 h-3" />
        delete
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table header
// ---------------------------------------------------------------------------

function TableHeader() {
  return (
    <div className="flex items-center gap-4 px-5 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
      <span className="flex-1 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        name
      </span>
      <span className="w-28 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        prefix
      </span>
      <span className="w-44 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        scopes
      </span>
      <span className="w-28 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        created
      </span>
      <span className="w-24 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        last used
      </span>
      <span className="w-20 flex-shrink-0 text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
        requests
      </span>
      <span className="w-16 flex-shrink-0" />
    </div>
  );
}

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
  const { data: plan } = usePlan();
  const maxApiKeys = plan?.limits.api_keys === "unlimited" ? 999 : (plan?.limits.api_keys ?? 1);
  const canCreateKey = (count: number) => count < maxApiKeys;
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
            <code className={`text-[12px] ${keys.length >= maxApiKeys ? "text-[var(--color-error)]" : "text-[var(--color-text)]"}`}>
              {keys.length}/{maxApiKeys === 999 ? "∞" : maxApiKeys}
            </code>
          </span>
          {plan && (
            <span className="text-[var(--color-text-dim)]">
              plan:{" "}
              <code className="text-[12px] text-[var(--color-text)]">{plan.tier}</code>
            </span>
          )}
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
              disabled={!canCreateKey(keys.length)}
              title={
                !canCreateKey(keys.length)
                  ? `key limit reached (${maxApiKeys}/${maxApiKeys}). upgrade your plan to create more keys.`
                  : undefined
              }
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase disabled:opacity-40 disabled:cursor-not-allowed"
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
          <div className="mb-4 flex items-start gap-2 p-3 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 animate-fade-in">
            <AlertTriangle
              className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-error)] tracking-wider">
              {loadError}
            </p>
          </div>
        )}

        {/* Keys table or empty state */}
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          {keys.length === 0 ? (
            <EmptyState
              icon={EmptyList}
              title="no api keys"
              description="create a key to enable programmatic access to the signalpilot backend"
              action={
                !showCreateForm ? (
                  <button
                    onClick={() => setShowCreateForm(true)}
                    className="flex items-center gap-1.5 px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
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
  const MAX_KEYS = 50;

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
            <code className="text-[12px] text-[var(--color-text)]">
              {keys.length}/{MAX_KEYS}
            </code>
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
              disabled={keys.length >= MAX_KEYS}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase disabled:opacity-40 disabled:cursor-not-allowed"
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
          <div className="mb-4 flex items-start gap-2 p-3 border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 animate-fade-in">
            <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
            <p className="text-[12px] text-[var(--color-error)] tracking-wider">{loadError}</p>
          </div>
        )}

        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          {keys.length === 0 ? (
            <EmptyState
              icon={EmptyList}
              title="no api keys"
              description="create a key to enable programmatic access to the signalpilot gateway"
              action={
                !showCreateForm ? (
                  <button
                    onClick={() => setShowCreateForm(true)}
                    className="flex items-center gap-1.5 px-4 py-2 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
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
