// Pure state logic for the Connectors UI: health derivation, tool grouping
// and defaults, slug preview, and the URL-or-command parser. No React, no
// network, so every rule here is unit-testable and shared by the settings
// page, the chat settings panel, and the add flow.

import type {
  Connector,
  ConnectorScope,
  ToolAnnotations,
  ToolInfo,
} from "~/lib/api/mcp-connectors";

// ── Health (one value per row, fixed precedence) ─────────────────────────

export type HealthTone = "ok" | "attention" | "error" | "muted" | "pending";

export type ConnectorHealth = {
  /** Row label, e.g. "Connected". Copy from the stories' state table. */
  label: string;
  tone: HealthTone;
  /** One secondary line, or null. Never repeats the label. */
  detail: string | null;
  /** The one action that resolves the state, if any. */
  action: "sign_in" | "add_key" | "retry" | "review" | "turn_on" | null;
};

/**
 * Precedence, highest first: turned off (org, then me) → needs sign-in for
 * me → needs my key → unreachable → tools changed → connecting → connected.
 * Exactly one health value per row so the pill never stacks.
 */
export function deriveConnectorHealth(connector: Connector): ConnectorHealth {
  const me = connector.my_state;
  if (!connector.enabled) {
    return connector.scope === "org"
      ? { label: "Off", tone: "muted", detail: "Turned off by your organization", action: null }
      : { label: "Off", tone: "muted", detail: "Turned off by you", action: "turn_on" };
  }
  if (me && !me.enabled) {
    return { label: "Off", tone: "muted", detail: "Turned off by you", action: "turn_on" };
  }
  const needsMySignIn =
    connector.status === "needs_sign_in" ||
    (connector.auth === "oauth" && me !== null && !me.signed_in);
  if (needsMySignIn) {
    return { label: "Needs sign-in", tone: "attention", detail: null, action: "sign_in" };
  }
  const needsMyKey =
    connector.status === "needs_key" ||
    (connector.env_keys.some((key) => key.member_supplied) && me !== null && !me.has_key);
  if (needsMyKey) {
    return { label: "Needs your key", tone: "attention", detail: null, action: "add_key" };
  }
  if (connector.status === "unreachable") {
    return {
      label: "Unreachable",
      tone: "error",
      detail: connector.status_detail ?? "We couldn't reach this address",
      action: "retry",
    };
  }
  if (connector.status === "tools_changed") {
    return {
      label: "Tools changed",
      tone: "attention",
      detail: connector.status_detail ?? "New tools are waiting for review",
      action: "review",
    };
  }
  if (connector.status === "pending") {
    return {
      label: connector.transport === "stdio" ? "Starting…" : "Connecting…",
      tone: "pending",
      detail: null,
      action: null,
    };
  }
  if (connector.status === "disabled") {
    return { label: "Off", tone: "muted", detail: null, action: "turn_on" };
  }
  return { label: "Connected", tone: "ok", detail: null, action: null };
}

/** True when the agent will receive this connector's tools on its next run. */
export function isConnectorActiveForMe(connector: Connector): boolean {
  return deriveConnectorHealth(connector).tone === "ok";
}

/** "12 tools · 9 on", "1 tool", or "No tools yet". */
export function describeToolCount(total: number, on: number): string {
  if (total === 0) return "No tools yet";
  const noun = total === 1 ? "tool" : "tools";
  return on === total ? `${total} ${noun}` : `${total} ${noun} · ${on} on`;
}

/** Subtitle for a row: the host for remote connectors, the command otherwise. */
export function connectorSubtitle(connector: Connector): string {
  if (connector.url) return hostOf(connector.url) ?? connector.url;
  const command = [connector.command, ...connector.args].filter(Boolean).join(" ");
  return command || "—";
}

export function hostOf(url: string): string | null {
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

/** Ordering for the settings page: organization first, then personal, each by name. */
export function sortConnectors(connectors: Connector[]): Connector[] {
  return [...connectors].sort((a, b) =>
    a.scope !== b.scope
      ? a.scope === "org"
        ? -1
        : 1
      : a.name.localeCompare(b.name),
  );
}

// ── Tools ────────────────────────────────────────────────────────────────

export type ToolKind = "read" | "write" | "destructive";

/** Provider annotations are claims, not guarantees; the chip says which. */
export function toolKind(annotations: ToolAnnotations): ToolKind {
  if (annotations.destructive_hint) return "destructive";
  if (annotations.read_only_hint) return "read";
  return "write";
}

export const TOOL_KIND_LABEL: Record<ToolKind, string> = {
  read: "Read-only",
  write: "Writes",
  destructive: "Destructive",
};

/** Ranks for ordering inside a group: `risky_first` leads with Destructive. */
const KIND_RANK_RISKY_FIRST: Record<ToolKind, number> = { destructive: 0, write: 1, read: 2 };
const KIND_RANK_SAFE_FIRST: Record<ToolKind, number> = { read: 0, write: 1, destructive: 2 };

/**
 * Sort for a tool group: new tools first (so the review banner lines up
 * with them), then by kind, then by name. The On list leads with read-only
 * tools; the Off list leads with the write and destructive tools the user
 * most needs to see before turning anything on.
 */
export function sortToolsByKind(tools: ToolInfo[], order: "safe_first" | "risky_first"): ToolInfo[] {
  const rank = order === "safe_first" ? KIND_RANK_SAFE_FIRST : KIND_RANK_RISKY_FIRST;
  return [...tools].sort(
    (a, b) =>
      Number(b.is_new) - Number(a.is_new) ||
      rank[toolKind(a.annotations)] - rank[toolKind(b.annotations)] ||
      a.name.localeCompare(b.name),
  );
}

/** Counts per kind, for the filter chips ("Read-only 5 · Writes 6 · Destructive 2"). */
export function countToolKinds(tools: ToolInfo[]): Record<ToolKind | "all", number> {
  const counts = { all: tools.length, read: 0, write: 0, destructive: 0 };
  for (const tool of tools) counts[toolKind(tool.annotations)] += 1;
  return counts;
}

export function filterToolsByKind(tools: ToolInfo[], kind: ToolKind | "all"): ToolInfo[] {
  return kind === "all" ? tools : tools.filter((tool) => toolKind(tool.annotations) === kind);
}

/**
 * R3 defaults: read-only → on/auto; destructive or unannotated → off until
 * the user turns it on. Newly discovered tools are always off.
 */
export function defaultToolSetting(
  annotations: ToolAnnotations,
  isNew = false,
): { enabled: boolean; policy: "auto" | "off" } {
  if (isNew) return { enabled: false, policy: "off" };
  return toolKind(annotations) === "read"
    ? { enabled: true, policy: "auto" }
    : { enabled: false, policy: "off" };
}

export type ToolGroups = {
  on: ToolInfo[];
  off: ToolInfo[];
  fresh: ToolInfo[];
};

/**
 * Splits tools into the On / Off lists the drawer renders. New tools lead
 * each group so the review banner lines up with what it counts; inside the
 * On group read-only tools come first, inside Off the write and destructive
 * tools do (see `sortToolsByKind`). `disabledForMe` (a member's own tool
 * switches) overrides the org policy.
 */
export function groupTools(
  tools: ToolInfo[],
  disabledForMe: string[] = [],
): ToolGroups {
  const mine = new Set(disabledForMe);
  const isOn = (tool: ToolInfo) => tool.enabled && !mine.has(tool.name);
  return {
    on: sortToolsByKind(tools.filter(isOn), "safe_first"),
    off: sortToolsByKind(tools.filter((tool) => !isOn(tool)), "risky_first"),
    fresh: sortToolsByKind(tools.filter((tool) => tool.is_new), "risky_first"),
  };
}

/** The `PUT /tools` body for the bulk actions. */
export function bulkToolSettings(
  tools: ToolInfo[],
  action: "on_read_only" | "off_all",
): Record<string, { enabled: boolean; policy: "auto" | "off" }> {
  const next: Record<string, { enabled: boolean; policy: "auto" | "off" }> = {};
  for (const tool of tools) {
    const on = action === "on_read_only" ? toolKind(tool.annotations) === "read" : false;
    next[tool.name] = on ? { enabled: true, policy: "auto" } : { enabled: false, policy: "off" };
  }
  return next;
}

export function filterTools(tools: ToolInfo[], query: string): ToolInfo[] {
  const q = query.trim().toLowerCase();
  if (!q) return tools;
  return tools.filter(
    (tool) =>
      tool.name.toLowerCase().includes(q) ||
      (tool.title ?? "").toLowerCase().includes(q) ||
      tool.description.toLowerCase().includes(q),
  );
}

// ── Slug (R9: one rule, stated once) ─────────────────────────────────────

/** kebab/snake of the display name, `[a-z0-9_]{2,40}`. */
export function slugify(name: string): string {
  const base = name
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_{2,}/g, "_")
    .slice(0, 40)
    .replace(/_+$/g, "");
  return base.length >= 2 ? base : base ? `${base}_server` : "";
}

/**
 * Slug the gateway will assign at creation: a personal slug that collides
 * with an org slug gets `_mine` appended (shown before save, never renamed
 * later). Returns null when the name yields no valid slug.
 */
export function previewSlug(
  name: string,
  scope: ConnectorScope,
  existing: Pick<Connector, "slug" | "scope">[],
): { slug: string; suffixed: boolean; taken: boolean } | null {
  const base = slugify(name);
  if (!base) return null;
  const orgSlugs = new Set(existing.filter((c) => c.scope === "org").map((c) => c.slug));
  const sameScope = new Set(existing.filter((c) => c.scope === scope).map((c) => c.slug));
  if (scope === "personal" && orgSlugs.has(base)) {
    const slug = `${base.slice(0, 35)}_mine`;
    return { slug, suffixed: true, taken: sameScope.has(slug) };
  }
  return { slug: base, suffixed: false, taken: sameScope.has(base) };
}

// ── Add flow: URL or command ─────────────────────────────────────────────

export type ServerInput =
  | { kind: "url"; url: string }
  | { kind: "command"; command: string; args: string[] }
  | { kind: "empty" }
  | { kind: "invalid"; reason: string };

const BLOCKED_COMMANDS: Record<string, string> = {
  docker: "Docker can't run inside the sandbox. Use an npx or uvx command, or a server URL.",
};

/** Auto-detects an address versus a command. The user can override the mode. */
export function parseServerInput(raw: string): ServerInput {
  const text = raw.trim();
  if (!text) return { kind: "empty" };
  if (/^https?:\/\//i.test(text)) {
    try {
      const url = new URL(text);
      if (!url.host) throw new Error("no host");
      return { kind: "url", url: url.toString() };
    } catch {
      return { kind: "invalid", reason: "That doesn't look like a complete address." };
    }
  }
  if (/^[a-z0-9.-]+\.[a-z]{2,}(\/\S*)?$/i.test(text)) {
    return { kind: "url", url: `https://${text}` };
  }
  const parts = splitCommand(text);
  const command = parts[0] ?? "";
  if (!command) return { kind: "empty" };
  if (BLOCKED_COMMANDS[command]) {
    return { kind: "invalid", reason: BLOCKED_COMMANDS[command] };
  }
  return { kind: "command", command, args: parts.slice(1) };
}

/** Shell-style split honoring single and double quotes. */
export function splitCommand(text: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) out.push(match[1] ?? match[2] ?? match[3]);
  return out;
}

/** Turn a probe/server name into a display name ("mcp.linear.app" → "Linear"). */
export function suggestName(input: ServerInput, serverName?: string | null): string {
  if (serverName?.trim()) {
    // "github-mcp-server" → "Github"; "Atlassian Rovo MCP" → "Atlassian Rovo".
    const stripped = serverName.replace(/(^|[-_ ])(mcp|server)(?=[-_ ]|$)/gi, " ").trim();
    return titleCase(stripped || serverName.trim());
  }
  if (input.kind === "url") {
    const host = hostOf(input.url) ?? "";
    const parts = host.split(".").filter((p) => !/^(www|mcp|api|app)$/i.test(p));
    const core = parts.length >= 2 ? parts[parts.length - 2] : parts[0];
    return core ? titleCase(core) : "New connector";
  }
  if (input.kind === "command") {
    const pkg = input.args.find((a) => /^@?[\w.-]+(\/[\w.-]+)?$/.test(a) && !a.startsWith("-"));
    const leaf = (pkg ?? input.command).split("/").pop() ?? "";
    return titleCase(leaf.replace(/^(server|mcp)[-_]/, "").replace(/[-_](server|mcp)$/, ""));
  }
  return "";
}

/** Brands whose casing a plain title-case gets wrong. Applied per word. */
const BRAND_CASE: Record<string, string> = {
  github: "GitHub",
  gitlab: "GitLab",
  linkedin: "LinkedIn",
  hubspot: "HubSpot",
  bigquery: "BigQuery",
  duckdb: "DuckDB",
  postgresql: "PostgreSQL",
  mongodb: "MongoDB",
  youtube: "YouTube",
  paypal: "PayPal",
  openai: "OpenAI",
  dbt: "dbt",
};

function titleCase(value: string): string {
  return value
    .replace(/[-_]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((w) => BRAND_CASE[w.toLowerCase()] ?? w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

/** "5 connectors · 22 tools go to your next chat" for the chat panel header. */
export function describeNextChatTools(connectors: Connector[]): string {
  const active = connectors.filter(isConnectorActiveForMe);
  const tools = active.reduce(
    (sum, c) => sum + Math.max(0, c.enabled_tool_count - (c.my_state?.disabled_tools.length ?? 0)),
    0,
  );
  if (active.length === 0) return "Nothing goes to your next chat yet.";
  const noun = active.length === 1 ? "connector" : "connectors";
  return `${active.length} ${noun} · ${tools} ${tools === 1 ? "tool goes" : "tools go"} to your next chat`;
}
