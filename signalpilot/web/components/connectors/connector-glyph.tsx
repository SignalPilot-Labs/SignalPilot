"use client";

import { Building2, Terminal, User } from "lucide-react";
import { useEffect, useState } from "react";
import { GATEWAY_URL, getAuthHeaders } from "~/lib/api/client";
import type { Connector } from "~/lib/api/mcp-connectors";
import { brandIcon, brandIconKeyForHost } from "~/lib/connector-brand-icons";
import { hostOf } from "~/lib/mcp-connectors-state";

type GlyphConnector = Pick<Connector, "name" | "url" | "transport"> &
  Partial<Pick<Connector, "icon_url" | "scope" | "command" | "args">>;

/** Absolute image source for `icon_url` (gateway-relative, absolute, or data:). */
export function resolveIconUrl(iconUrl: string | null | undefined): string | null {
  if (!iconUrl) return null;
  if (/^(data:|blob:|https?:)/i.test(iconUrl)) return iconUrl;
  return `${GATEWAY_URL}${iconUrl.startsWith("/") ? "" : "/"}${iconUrl}`;
}

// The gateway icon route is scope-protected, and a browser <img> sends no
// Authorization header, so gateway-relative icons are fetched with the API
// credentials and shown through an object URL. Shared per URL across rows.
const iconObjectUrls = new Map<string, Promise<string | null>>();

function loadGatewayIcon(url: string): Promise<string | null> {
  let pending = iconObjectUrls.get(url);
  if (!pending) {
    pending = (async () => {
      try {
        const res = await fetch(url, { headers: await getAuthHeaders() });
        if (!res.ok || !res.headers.get("content-type")?.startsWith("image/")) return null;
        return URL.createObjectURL(await res.blob());
      } catch {
        return null;
      }
    })();
    iconObjectUrls.set(url, pending);
  }
  return pending;
}

/** Resolves `icon_url` to something an <img> can render, or null once known unavailable. */
function useIconSrc(iconUrl: string | null | undefined, enabled: boolean): string | null {
  const resolved = enabled ? resolveIconUrl(iconUrl) : null;
  const needsFetch = !!resolved && resolved.startsWith(GATEWAY_URL);
  const [fetched, setFetched] = useState<{ url: string; src: string | null } | null>(null);
  useEffect(() => {
    if (!needsFetch || !resolved) return;
    let active = true;
    void loadGatewayIcon(resolved).then((src) => {
      if (active) setFetched({ url: resolved, src });
    });
    return () => {
      active = false;
    };
  }, [needsFetch, resolved]);
  if (!resolved) return null;
  if (!needsFetch) return resolved;
  return fetched?.url === resolved ? fetched.src : null;
}

/**
 * Service glyph, in order of preference:
 *   1. a curated inline SVG for well-known hosts (no network, CSP-proof);
 *   2. the gateway-proxied favicon from `icon_url` (same-origin, cached);
 *   3. a letter tile tinted by scope, with a small building (organization)
 *      or person (personal) mark in the corner so the fallback still says
 *      who the connector belongs to. Sandbox connectors show a terminal.
 * The tile renders underneath the image, so a slow icon never leaves a hole.
 */
export function ConnectorGlyph({
  connector,
  size = 36,
  className = "",
}: {
  connector: GlyphConnector;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const host = connector.url ? hostOf(connector.url) : null;
  const packageName = connector.transport === "stdio" ? [connector.command, ...(connector.args ?? [])].join(" ") : null;
  const curated = brandIcon(brandIconKeyForHost(host) ?? brandIconKeyForHost(packageName));
  const src = useIconSrc(connector.icon_url, !curated && !failed);
  const letter = connector.name.trim().charAt(0).toUpperCase() || "?";
  const scope = connector.scope ?? null;
  const tint =
    scope === "org"
      ? "border-[var(--color-success)]/25 bg-[var(--color-success)]/[0.07] text-[var(--color-success)]"
      : scope === "personal"
        ? "border-[var(--color-border)] bg-[var(--color-bg-elevated)] text-[var(--color-text-muted)]"
        : "border-[var(--color-border)] bg-[var(--color-bg-elevated)] text-[var(--color-text-muted)]";
  const ScopeMark = scope === "org" ? Building2 : scope === "personal" ? User : null;
  const markSize = Math.max(8, Math.round(size * 0.3));
  const showMark = ScopeMark && !curated && !src && size >= 28;

  return (
    <span
      aria-hidden="true"
      data-testid="connector-glyph"
      data-glyph={curated ? `brand:${curated.key}` : src ? "icon" : connector.transport === "stdio" ? "terminal" : "letter"}
      style={{ width: size, height: size }}
      className={`relative flex flex-none items-center justify-center rounded-[10px] border ${tint} ${className}`}
    >
      {curated ? (
        <svg
          viewBox={curated.viewBox}
          style={{ width: size * 0.6, height: size * 0.6 }}
          className={curated.background ? "rounded-[4px]" : ""}
          dangerouslySetInnerHTML={{
            __html: curated.background
              ? `<rect width="100%" height="100%" rx="4" fill="${curated.background}"/>${curated.body}`
              : curated.body,
          }}
        />
      ) : connector.transport === "stdio" ? (
        <Terminal style={{ width: size * 0.45, height: size * 0.45 }} />
      ) : (
        <span className="font-mono font-medium" style={{ fontSize: Math.round(size * 0.42) }}>
          {letter}
        </span>
      )}
      {src && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full rounded-[9px] bg-[var(--color-bg-elevated)] object-contain p-[20%]"
        />
      )}
      {showMark && (
        <span
          className={`absolute -bottom-1 -right-1 flex items-center justify-center rounded-full border border-[var(--color-bg)] ${
            scope === "org" ? "bg-[var(--color-success)] text-[var(--color-bg)]" : "bg-[var(--color-bg-elevated)] text-[var(--color-text-muted)]"
          }`}
          style={{ width: markSize + 6, height: markSize + 6 }}
          data-testid="connector-glyph-scope"
        >
          <ScopeMark style={{ width: markSize - 1, height: markSize - 1 }} strokeWidth={2.2} />
        </span>
      )}
    </span>
  );
}
