"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Key,
  Plug,
  Terminal,
  Copy,
  CheckCircle2,
  Loader2,
  Info,
  ExternalLink,
} from "lucide-react";
import { useAppAuth } from "@/lib/auth-context";
import { useBackendClient } from "@/lib/backend-client";
import type { ApiKeyResponse } from "@/lib/backend-client";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { CodeBlock } from "@/components/ui/code-block";
import { StatusDot } from "@/components/ui/data-viz";
import { SectionHeader } from "@/components/ui/section-header";

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

function getClaudeDesktopConfig(mcpUrl: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        signalpilot: {
          url: mcpUrl,
          headers: {
            Authorization: "Bearer sp_your_api_key_here",
          },
        },
      },
    },
    null,
    2,
  );
}

function getCursorConfig(mcpUrl: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        signalpilot: {
          url: mcpUrl,
          headers: {
            Authorization: "Bearer sp_your_api_key_here",
          },
        },
      },
    },
    null,
    2,
  );
}

function getGenericHttpConfig(mcpUrl: string): string {
  return JSON.stringify(
    {
      url: mcpUrl,
      transport: "streamable-http",
      headers: {
        Authorization: "Bearer sp_your_api_key_here",
      },
    },
    null,
    2,
  );
}

// ---------------------------------------------------------------------------
// Tab types
// ---------------------------------------------------------------------------

type ClientTab = "claude-desktop" | "cursor" | "generic-http";

const CLIENT_TABS: { id: ClientTab; label: string; filename: string }[] = [
  { id: "claude-desktop", label: "claude desktop", filename: "claude_desktop_config.json" },
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
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  if (!isCloudMode) {
    return (
      <div className="p-8 max-w-3xl animate-fade-in">
        <PageHeader
          title="mcp connect"
          subtitle="integration"
          description="connect mcp clients to signalpilot using your api key"
        />
        <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)]">
          <div className="p-6 flex items-start gap-3">
            <Info
              className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0"
              strokeWidth={1.5}
            />
            <p className="text-[12px] text-[var(--color-text-dim)] tracking-wider leading-relaxed">
              mcp client configuration is available in cloud mode. set{" "}
              <code className="text-[var(--color-text-muted)]">
                NEXT_PUBLIC_DEPLOYMENT_MODE=cloud
              </code>{" "}
              and configure clerk to enable this feature.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return <McpConnectContent />;
}

// ---------------------------------------------------------------------------
// Content component — safe to call useBackendClient() (ClerkProvider present)
// ---------------------------------------------------------------------------

function McpConnectContent() {
  const { isLoaded } = useAppAuth();
  const client = useBackendClient();
  const mcpUrl = getMcpUrl();

  const [keys, setKeys] = useState<ApiKeyResponse[]>([]);
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysError, setKeysError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ClientTab>("claude-desktop");

  const fetchKeys = useCallback(async () => {
    setKeysError(null);
    try {
      const data = await client.getApiKeys();
      setKeys(data);
    } catch (e) {
      setKeysError(String(e));
    } finally {
      setKeysLoading(false);
    }
  }, [client]);

  useEffect(() => {
    if (isLoaded) {
      fetchKeys();
    }
  }, [isLoaded, fetchKeys]);

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (!isLoaded || keysLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-dim)]" />
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Config snippet for active tab
  // ---------------------------------------------------------------------------

  function getActiveConfig(): string {
    switch (activeTab) {
      case "claude-desktop":
        return getClaudeDesktopConfig(mcpUrl);
      case "cursor":
        return getCursorConfig(mcpUrl);
      case "generic-http":
        return getGenericHttpConfig(mcpUrl);
    }
  }

  const firstKey = keys.length > 0 ? keys[0] : null;

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
              <span className="text-[var(--color-text-muted)] font-mono">bearer token</span>
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
