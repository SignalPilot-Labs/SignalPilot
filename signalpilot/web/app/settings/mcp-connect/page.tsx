"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Key,
  Plug,
  Terminal,
  Copy,
  CheckCircle2,
  Info,
  ExternalLink,
} from "lucide-react";
import { useAppAuth } from "@/lib/auth-context";
import { useBackendClient } from "@/lib/backend-client";
import type { ApiKeyResponse } from "@/lib/backend-client";
import { getGatewayApiKeys } from "@/lib/api";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { CodeBlock } from "@/components/ui/code-block";
import { StatusDot } from "@/components/ui/data-viz";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { ApiKeysSkeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// MCP URL derivation
// ---------------------------------------------------------------------------

function getMcpUrl(): string {
  return (
    process.env.NEXT_PUBLIC_MCP_URL ||
    `${process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300"}/mcp`
  );
}

// ---------------------------------------------------------------------------
// Config snippet generators
// ---------------------------------------------------------------------------

function buildHeaders(hasKeys: boolean): Record<string, string> | undefined {
  if (!hasKeys) return undefined;
  return { "X-API-Key": "sp_your_api_key_here" };
}

function getClaudeConfig(mcpUrl: string, hasKeys: boolean): string {
  const entry: Record<string, unknown> = { type: "http", url: mcpUrl };
  const headers = buildHeaders(hasKeys);
  if (headers) entry.headers = headers;
  return JSON.stringify({ mcpServers: { signalpilot: entry } }, null, 2);
}

function getCursorConfig(mcpUrl: string, hasKeys: boolean): string {
  const entry: Record<string, unknown> = { url: mcpUrl };
  const headers = buildHeaders(hasKeys);
  if (headers) entry.headers = headers;
  return JSON.stringify({ mcpServers: { signalpilot: entry } }, null, 2);
}

function getGenericHttpConfig(mcpUrl: string, hasKeys: boolean): string {
  const cfg: Record<string, unknown> = { url: mcpUrl, transport: "streamable-http" };
  const headers = buildHeaders(hasKeys);
  if (headers) cfg.headers = headers;
  return JSON.stringify(cfg, null, 2);
}

// ---------------------------------------------------------------------------
// Tab types
// ---------------------------------------------------------------------------

type ClientTab = "claude" | "cursor" | "generic-http";

const CLIENT_TABS: { id: ClientTab; label: string; filename: string }[] = [
  { id: "claude", label: "claude code / desktop", filename: ".mcp.json" },
  { id: "cursor", label: "cursor", filename: ".cursor/mcp.json" },
  { id: "generic-http", label: "generic http", filename: "config.json" },
];


// ---------------------------------------------------------------------------
// URL copy button — inline for the endpoint section
// ---------------------------------------------------------------------------

function UrlCopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider flex-shrink-0"
      title="copy url"
    >
      {copied ? (
        <>
          <CheckCircle2 className="w-3 h-3 text-[var(--color-success)]" />
          <span className="text-[var(--color-success)]">copied</span>
        </>
      ) : (
        <>
          <Copy className="w-3 h-3" />
          copy
        </>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Gate component — checks isCloudMode before rendering content
// ---------------------------------------------------------------------------

export default function McpConnectPage() {
  const { isCloudMode, isLoaded } = useAppAuth();

  if (!isLoaded) {
    return <ApiKeysSkeleton />;
  }

  if (isCloudMode) {
    return <McpConnectContent />;
  }

  return <LocalMcpConnectContent />;
}

// ---------------------------------------------------------------------------
// Content component — safe to call useBackendClient() (ClerkProvider present)
// ---------------------------------------------------------------------------

function McpConnectContent() {
  const { isLoaded } = useAppAuth();
  const client = useBackendClient();
  const mcpUrl = getMcpUrl();
  const { toast } = useToast();

  const [keys, setKeys] = useState<ApiKeyResponse[]>([]);
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysError, setKeysError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ClientTab>("claude");

  const fetchKeys = useCallback(async () => {
    setKeysError(null);
    try {
      const data = await client.getApiKeys();
      setKeys(data);
    } catch (e) {
      setKeysError(String(e));
      toast("failed to load api keys", "error");
    } finally {
      setKeysLoading(false);
    }
  }, [client, toast]);

  useEffect(() => {
    if (isLoaded) {
      fetchKeys();
    }
  }, [isLoaded, fetchKeys]);

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (!isLoaded || keysLoading) {
    return <ApiKeysSkeleton />;
  }

  // ---------------------------------------------------------------------------
  // Config snippet for active tab
  // ---------------------------------------------------------------------------

  const hasKeys = keys.length > 0;
  const firstKey = hasKeys ? keys[0] : null;

  function getActiveConfig(): string {
    switch (activeTab) {
      case "claude":
        return getClaudeConfig(mcpUrl, hasKeys);
      case "cursor":
        return getCursorConfig(mcpUrl, hasKeys);
      case "generic-http":
        return getGenericHttpConfig(mcpUrl, hasKeys);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="mcp connect"
        subtitle="integration"
        description="connect mcp clients to signalpilot using your api key"
      />

      <TerminalBar
        path="settings/mcp-connect --config"
        status={<StatusDot status="healthy" size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            transport:{" "}
            <code className="text-[12px] text-[var(--color-text)]">streamable-http</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            protocol:{" "}
            <code className="text-[12px] text-[var(--color-text)]">mcp/1.0</code>
          </span>
        </div>
      </TerminalBar>

      {/* ── Section 1: Endpoint ── */}
      <section className="mb-8">
        <SectionHeader icon={Plug} title="endpoint" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 space-y-4">
          {/* URL row */}
          <div>
            <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-2">
              mcp server url
            </p>
            <div className="flex items-center gap-3">
              <code className="flex-1 px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] text-[var(--color-success)] tracking-wider font-mono break-all">
                {mcpUrl}
              </code>
              <UrlCopyButton text={mcpUrl} />
            </div>
          </div>

          {/* Transport metadata */}
          <div className="flex items-center gap-6 text-[11px] text-[var(--color-text-dim)] tracking-wider pt-1">
            <span>
              transport:{" "}
              <span className="text-[var(--color-text-muted)] font-mono">streamable-http</span>
            </span>
            <span>
              auth:{" "}
              <span className="text-[var(--color-text-muted)] font-mono">X-API-Key</span>
            </span>
            <span>
              method:{" "}
              <span className="text-[var(--color-text-muted)] font-mono">POST</span>
            </span>
          </div>
        </div>
      </section>

      {/* ── Section 2: API Key ── */}
      <section className="mb-8">
        <SectionHeader icon={Key} title="api key" />
        {keysError ? (
          <div className="border border-[var(--color-error)]/20 bg-[var(--color-error)]/5 p-4 flex items-start gap-3">
            <Info
              className="w-3.5 h-3.5 text-[var(--color-error)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-error)] tracking-wider">{keysError}</p>
          </div>
        ) : firstKey ? (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <Key
                  className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0"
                  strokeWidth={1.5}
                />
                <div className="min-w-0">
                  <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-1">
                    active key
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="text-[13px] text-[var(--color-text-muted)] tracking-wider font-mono">
                      {firstKey.prefix}...
                    </code>
                    <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider truncate max-w-[120px]">
                      ({firstKey.name})
                    </span>
                  </div>
                </div>
              </div>
              <Link
                href="/settings/api-keys"
                className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider flex-shrink-0"
              >
                <ExternalLink className="w-3 h-3" />
                manage keys
              </Link>
            </div>
            {keys.length > 1 && (
              <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider mt-3 pt-3 border-t border-[var(--color-border)]">
                {keys.length - 1} additional{" "}
                {keys.length - 1 === 1 ? "key" : "keys"} available —{" "}
                <Link
                  href="/settings/api-keys"
                  className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors underline underline-offset-2"
                >
                  view all
                </Link>
              </p>
            )}
          </div>
        ) : (
          <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
            <div className="flex items-start gap-3">
              <Info
                className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
                strokeWidth={1.5}
              />
              <div className="flex-1">
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed mb-3">
                  you don&apos;t have any api keys yet. create one to use with mcp clients.
                </p>
                <Link
                  href="/settings/api-keys"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
                >
                  <Key className="w-3 h-3" />
                  create api key
                </Link>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* ── Section 3: Client Configuration ── */}
      <section className="mb-8">
        <SectionHeader icon={Terminal} title="client configuration" />

        {/* Tab selector */}
        <div role="tablist" className="flex items-center gap-0 mb-4 border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          {CLIENT_TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                role="tab"
                aria-selected={isActive}
                aria-controls={`tabpanel-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                className={`flex-1 px-4 py-2.5 text-[12px] tracking-wider transition-all border-r last:border-r-0 border-[var(--color-border)] ${
                  isActive
                    ? "text-[var(--color-text)] bg-[var(--color-bg-hover)] border-b-2 border-b-[var(--color-text)]"
                    : "text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Tab content */}
        <div role="tabpanel" id={`tabpanel-${activeTab}`}>
          {/* Filename indicator */}
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider uppercase">
              file:
            </span>
            <code className="text-[12px] text-[var(--color-text-muted)] tracking-wider">
              {CLIENT_TABS.find((t) => t.id === activeTab)?.filename}
            </code>
          </div>

          {/* Code block */}
          <CodeBlock
            code={getActiveConfig()}
            language="json"
            maxHeight="20rem"
            showLineNumbers={true}
          />

          {/* Usage hint */}
          <div className="mt-4 flex items-start gap-2 p-3 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
            <Info
              className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
              replace{" "}
              <code className="text-[var(--color-text-muted)]">sp_your_api_key_here</code> with
              your actual api key from{" "}
              <Link
                href="/settings/api-keys"
                className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors underline underline-offset-2"
              >
                settings / api keys
              </Link>
              . the full key is only shown once at creation time.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Local mode — fetches keys from gateway, shows no-auth config when no keys
// ---------------------------------------------------------------------------

function LocalMcpConnectContent() {
  const mcpUrl = getMcpUrl();
  const { toast } = useToast();

  const [keys, setKeys] = useState<ApiKeyResponse[]>([]);
  const [keysLoading, setKeysLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<ClientTab>("claude");

  const fetchKeys = useCallback(async () => {
    try {
      const data = await getGatewayApiKeys();
      setKeys(data);
    } catch {
      // No keys or gateway unreachable — that's fine for local
    } finally {
      setKeysLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  if (keysLoading) {
    return <ApiKeysSkeleton />;
  }

  const hasKeys = keys.length > 0;
  const firstKey = hasKeys ? keys[0] : null;

  function getActiveConfig(): string {
    switch (activeTab) {
      case "claude":
        return getClaudeConfig(mcpUrl, hasKeys);
      case "cursor":
        return getCursorConfig(mcpUrl, hasKeys);
      case "generic-http":
        return getGenericHttpConfig(mcpUrl, hasKeys);
    }
  }

  return (
    <div className="p-8 max-w-3xl animate-fade-in">
      <PageHeader
        title="mcp connect"
        subtitle="integration"
        description="connect mcp clients to your local signalpilot instance"
      />

      <TerminalBar
        path="settings/mcp-connect --config"
        status={<StatusDot status="healthy" size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">
            transport: <code className="text-[12px] text-[var(--color-text)]">streamable-http</code>
          </span>
          <span className="text-[var(--color-text-dim)]">
            auth: <code className="text-[12px] text-[var(--color-text)]">{hasKeys ? "X-API-Key" : "none"}</code>
          </span>
        </div>
      </TerminalBar>

      {/* Endpoint */}
      <section className="mb-8">
        <SectionHeader icon={Plug} title="endpoint" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5 space-y-4">
          <div>
            <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-2">mcp server url</p>
            <div className="flex items-center gap-3">
              <code className="flex-1 px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] text-[13px] text-[var(--color-success)] tracking-wider font-mono break-all">
                {mcpUrl}
              </code>
              <UrlCopyButton text={mcpUrl} />
            </div>
          </div>
          <div className="flex items-center gap-6 text-[11px] text-[var(--color-text-dim)] tracking-wider pt-1">
            <span>transport: <span className="text-[var(--color-text-muted)] font-mono">streamable-http</span></span>
            <span>auth: <span className="text-[var(--color-text-muted)] font-mono">{hasKeys ? "X-API-Key" : "none (no api key set)"}</span></span>
          </div>
        </div>
      </section>

      {/* API Key status */}
      <section className="mb-8">
        <SectionHeader icon={Key} title="authentication" />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
          {firstKey ? (
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <Key className="w-3.5 h-3.5 text-[var(--color-text-dim)] flex-shrink-0" strokeWidth={1.5} />
                <div className="min-w-0">
                  <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.15em] mb-1">active key</p>
                  <div className="flex items-center gap-2">
                    <code className="text-[13px] text-[var(--color-text-muted)] tracking-wider font-mono">{firstKey.prefix}...</code>
                    <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider truncate max-w-[120px]">({firstKey.name})</span>
                  </div>
                </div>
              </div>
              <Link href="/settings/api-keys" className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider flex-shrink-0">
                <ExternalLink className="w-3 h-3" /> manage keys
              </Link>
            </div>
          ) : (
            <div className="flex items-start gap-3">
              <Info className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
              <div className="flex-1">
                <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed mb-1">
                  no api key configured — mcp clients can connect without authentication.
                </p>
                <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
                  to require auth, <Link href="/settings/api-keys" className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] underline underline-offset-2">create an api key</Link> and it will be enforced automatically.
                </p>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Client Configuration */}
      <section className="mb-8">
        <SectionHeader icon={Terminal} title="client configuration" />
        <div role="tablist" className="flex items-center gap-0 mb-4 border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
          {CLIENT_TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button key={tab.id} role="tab" aria-selected={isActive} onClick={() => setActiveTab(tab.id)}
                className={`flex-1 px-4 py-2.5 text-[12px] tracking-wider transition-all border-r last:border-r-0 border-[var(--color-border)] ${
                  isActive ? "text-[var(--color-text)] bg-[var(--color-bg-hover)] border-b-2 border-b-[var(--color-text)]" : "text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)]"
                }`}>
                {tab.label}
              </button>
            );
          })}
        </div>
        <div role="tabpanel">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider uppercase">file:</span>
            <code className="text-[12px] text-[var(--color-text-muted)] tracking-wider">{CLIENT_TABS.find((t) => t.id === activeTab)?.filename}</code>
          </div>
          <CodeBlock code={getActiveConfig()} language="json" maxHeight="20rem" showLineNumbers={true} />
          {hasKeys && (
            <div className="mt-4 flex items-start gap-2 p-3 border border-[var(--color-border)] bg-[var(--color-bg-card)]">
              <Info className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
              <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
                replace <code className="text-[var(--color-text-muted)]">sp_your_api_key_here</code> with your api key from{" "}
                <Link href="/settings/api-keys" className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] underline underline-offset-2">settings / api keys</Link>.
              </p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
