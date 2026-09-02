// A small curated set of provider marks for the Connectors glyph, keyed by
// well-known hosts. Rendered inline (no network, no CSP exposure) before the
// gateway-proxied favicon is tried. Each mark is a simplified, recognizable
// silhouette in the provider's primary color; the letter tile remains the
// honest fallback for everything else.

export type BrandIcon = {
  key: string;
  viewBox: string;
  /** Background behind the mark; null keeps the tile's own surface. */
  background: string | null;
  /** `<path d>`/shape markup, already colored. */
  body: string;
};

const ICONS: BrandIcon[] = [
  {
    key: "github",
    viewBox: "0 0 24 24",
    background: null,
    body:
      '<path fill="#e6edf3" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>',
  },
  {
    key: "atlassian",
    viewBox: "0 0 24 24",
    background: null,
    body:
      '<path fill="#2684ff" d="M11.53 2.3a.7.7 0 0 1 .94 0l8.2 8.2a.7.7 0 0 1 0 .99l-8.2 8.2a.7.7 0 0 1-.94 0l-8.2-8.2a.7.7 0 0 1 0-.99z"/><path fill="#0052cc" d="M12 6.4 6.9 11.5 12 16.6l5.1-5.1z"/><path fill="#8fbcff" d="M12 9.6 9.9 11.7l2.1 2.1 2.1-2.1z"/>',
  },
  {
    key: "slack",
    viewBox: "0 0 24 24",
    background: null,
    body:
      '<rect x="9.1" y="2" width="3.4" height="9" rx="1.7" fill="#36c5f0"/><rect x="13" y="2" width="9" height="3.4" rx="1.7" fill="#2eb67d"/><rect x="11.5" y="13" width="3.4" height="9" rx="1.7" fill="#ecb22e"/><rect x="2" y="18.6" width="9" height="3.4" rx="1.7" fill="#e01e5a"/><rect x="2" y="9.1" width="9" height="3.4" rx="1.7" fill="#e01e5a" opacity=".85"/><rect x="13" y="11.5" width="9" height="3.4" rx="1.7" fill="#36c5f0" opacity=".85"/>',
  },
  {
    key: "linear",
    viewBox: "0 0 24 24",
    background: null,
    body:
      '<path fill="#5e6ad2" d="M2.1 13.6 10.4 21.9A10 10 0 0 1 2.1 13.6zm-.1-2.9L13.3 21.9c.9-.2 1.7-.5 2.5-.9L3 8.2c-.4.8-.7 1.6-1 2.5zm2-4.6L17.9 19.9c.6-.5 1.2-1 1.7-1.6L5.6 4.4c-.6.5-1.1 1.1-1.6 1.7zm3.2-3L21.1 15.3A10 10 0 1 0 7.2 3.1z"/>',
  },
  {
    key: "notion",
    viewBox: "0 0 24 24",
    background: "#ffffff",
    body:
      '<path fill="#111" d="M6.5 5.2 15.9 4.5c1.2-.1 1.5.1 2.2.6l3 2.1c.5.4.7.5.7 1v11.4c0 .9-.3 1.4-1.5 1.5l-10.9.7c-.9.1-1.3-.1-1.8-.7L4.1 17.9c-.5-.7-.7-1.2-.7-1.8V6.6c0-.7.3-1.3 1.1-1.4zm.4 1.6c-.5.1-.6.2-.4.6l1.3 1.7c.2.2.5.3.9.2l9.1-.6c.4 0 .5-.2.3-.5L16.8 6.6c-.2-.3-.5-.4-1-.4zm9.4 4.4v7.2c0 .4-.1.7-.6.7L6.7 19.6c-.5 0-.7-.2-.7-.6v-7.1c0-.4.1-.6.6-.6l8.9-.6c.5 0 .8.1.8.5zm-6.8 2.1 1.6 2.6v-2.6c0-.3-.1-.4-.4-.4l-1.8.1c-.3 0-.3.2-.2.4l3.5 5.4c.2.3.5.4.9.3l1-.1c.4 0 .5-.2.5-.5v-5.7c0-.3-.1-.4-.4-.4l-1.6.1c-.3 0-.4.2-.2.4l1.5 2.4v-.1l.1 2.9-3.3-5.2c-.2-.3-.4-.3-.8-.3z"/>',
  },
  {
    key: "snowflake",
    viewBox: "0 0 24 24",
    background: null,
    body:
      '<g stroke="#29b5e8" stroke-width="2.2" stroke-linecap="round" fill="none"><path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M12 3l-2.4 2.4M12 3l2.4 2.4M12 21l-2.4-2.4M12 21l2.4-2.4M4.2 7.5l3.3.9M4.2 7.5l.9 3.3M19.8 16.5l-3.3-.9M19.8 16.5l-.9-3.3M4.2 16.5l3.3-.9M4.2 16.5l.9-3.3M19.8 7.5l-3.3.9M19.8 7.5l-.9 3.3"/></g><rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1" transform="rotate(45 12 12)" fill="#29b5e8"/>',
  },
  {
    key: "google",
    viewBox: "0 0 24 24",
    background: null,
    body:
      '<path fill="#4285f4" d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.9h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.4z"/><path fill="#34a853" d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22z"/><path fill="#fbbc05" d="M6.4 14a6 6 0 0 1 0-3.9V7.5H3.1a10 10 0 0 0 0 9z"/><path fill="#ea4335" d="M12 5.9c1.5 0 2.8.5 3.8 1.5l2.8-2.8A10 10 0 0 0 3.1 7.5l3.3 2.6C7.2 7.8 9.4 5.9 12 5.9z"/>',
  },
];

const BY_KEY = new Map(ICONS.map((icon) => [icon.key, icon]));

/** Host (or bare provider name) → curated icon key; null when not curated. */
export function brandIconKeyForHost(host: string | null | undefined): string | null {
  if (!host) return null;
  const h = host.toLowerCase();
  if (/(^|\.)github\.com$/.test(h) || h.includes("github")) return "github";
  if (/(^|\.)atlassian\.(com|net)$/.test(h) || h.includes("jira") || h.includes("atlassian")) return "atlassian";
  if (/(^|\.)slack\.com$/.test(h) || h.includes("slack")) return "slack";
  if (/(^|\.)linear\.app$/.test(h) || h.includes("linear")) return "linear";
  if (/(^|\.)notion\.(so|com)$/.test(h) || h.includes("notion")) return "notion";
  if (/(^|\.)snowflake\.com$/.test(h)) return "snowflake";
  if (/(^|\.)google(apis)?\.com$/.test(h)) return "google";
  return null;
}

export function brandIcon(key: string | null | undefined): BrandIcon | null {
  return key ? BY_KEY.get(key) ?? null : null;
}

/** Standalone SVG markup for a curated icon (used to mint fixture data: URIs). */
export function brandIconSvg(key: string): string | null {
  const icon = BY_KEY.get(key);
  if (!icon) return null;
  const bg = icon.background ? `<rect width="100%" height="100%" rx="4" fill="${icon.background}"/>` : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${icon.viewBox}">${bg}${icon.body}</svg>`;
}

/** `data:image/svg+xml,…` for a curated icon, or null. */
export function brandIconDataUri(key: string): string | null {
  const svg = brandIconSvg(key);
  return svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : null;
}
