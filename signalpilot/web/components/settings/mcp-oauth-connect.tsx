"use client";

import { useState } from "react";
import { Copy, CheckCircle2, Info, LogIn, Terminal } from "lucide-react";
import { SectionHeader } from "~/components/ui/section-header";
import { CodeBlock } from "~/components/ui/code-block";

/**
 * "Sign in with SignalPilot" connection instructions for MCP clients.
 *
 * In cloud mode the gateway is an OAuth 2.1 resource server with Clerk as
 * the authorization server. An MCP client only needs the server URL: its
 * first request gets a 401 with a `WWW-Authenticate` challenge, it discovers
 * Clerk from `/.well-known/oauth-protected-resource/mcp`, registers itself
 * (dynamic client registration) and opens the Clerk sign-in + consent screen.
 * No API key is involved.
 */

function CopyButton({ text, label = "copy" }: { text: string; label?: string }) {
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
      className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors duration-150 flex-shrink-0"
      title={label}
    >
      {copied ? (
        <>
          <CheckCircle2 className="w-3 h-3 text-[var(--color-success)]" />
          <span className="text-[var(--color-success)]">copied</span>
        </>
      ) : (
        <>
          <Copy className="w-3 h-3" />
          {label}
        </>
      )}
    </button>
  );
}

export function claudeCodeAddCommand(mcpUrl: string): string {
  return `claude mcp add --transport http signalpilot ${mcpUrl}`;
}

export function oauthClientConfig(mcpUrl: string): string {
  return JSON.stringify({ mcpServers: { signalpilot: { type: "http", url: mcpUrl } } }, null, 2);
}

export function McpOAuthConnect({ mcpUrl }: { mcpUrl: string }) {
  const addCommand = claudeCodeAddCommand(mcpUrl);

  return (
    <section className="mb-8">
      <SectionHeader icon={LogIn} title="sign in with signalpilot (oauth)" />
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] rounded-[14px] p-5 space-y-5">
        <div>
          <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em] mb-2">
            mcp server url
          </p>
          <div className="flex items-center gap-3">
            <code className="flex-1 px-3 py-2.5 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[13px] text-[var(--color-success)] font-mono break-all">
              {mcpUrl}
            </code>
            <CopyButton text={mcpUrl} label="copy url" />
          </div>
          <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed mt-3">
            paste this url into any mcp client. the client opens the signalpilot sign-in page,
            you pick your organization, and the connection is authorized as you. no api key needed.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="border border-[var(--color-border)] rounded-[10px] p-4">
            <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em] mb-2">
              claude.ai / claude desktop
            </p>
            <ol className="text-[12px] text-[var(--color-text-muted)] leading-relaxed list-decimal pl-4 space-y-1">
              <li>settings → connectors → add custom connector</li>
              <li>paste the mcp server url above</li>
              <li>click connect and sign in with your signalpilot account</li>
            </ol>
          </div>
          <div className="border border-[var(--color-border)] rounded-[10px] p-4">
            <p className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em] mb-2">
              claude code
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 px-2.5 py-2 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[8px] text-[11px] text-[var(--color-text)] font-mono break-all">
                {addCommand}
              </code>
              <CopyButton text={addCommand} />
            </div>
            <p className="text-[11px] text-[var(--color-text-dim)] leading-relaxed mt-2">
              then run <code className="text-[var(--color-text-muted)]">/mcp</code> inside claude code to sign in.
            </p>
          </div>
        </div>

        <div>
          <div className="flex items-center gap-2 mb-2">
            <Terminal className="w-3.5 h-3.5 text-[var(--color-text-dim)]" strokeWidth={1.5} />
            <span className="text-[11px] text-[var(--color-text-dim)] tracking-wider uppercase">
              cursor / other clients (.mcp.json)
            </span>
          </div>
          <CodeBlock code={oauthClientConfig(mcpUrl)} language="json" maxHeight="12rem" showLineNumbers={false} />
        </div>

        <div className="flex items-start gap-2 p-3 border border-[var(--color-border)] bg-[var(--color-bg)] rounded-[10px]">
          <Info className="w-3.5 h-3.5 text-[var(--color-text-dim)] mt-0.5 flex-shrink-0" strokeWidth={1.5} />
          <p className="text-[12px] text-[var(--color-text-dim)] leading-relaxed">
            your access follows your organization role: admins get the full tool set, members get
            everything except admin-only tools. api keys below remain available for headless or
            ci usage.
          </p>
        </div>
      </div>
    </section>
  );
}
