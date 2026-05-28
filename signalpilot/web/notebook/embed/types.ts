import type { JotaiStore } from "@/core/state/jotai";
import type { ClientRegistries } from "./client-binding";

export type { JotaiStore };
export type { ClientRegistries };

/**
 * Options for creating a SignalpilotClient instance.
 */
export interface SignalpilotClientOptions {
  /**
   * Identifies this mount for future multi-instance support (Phase B/C).
   * Auto-generated if not provided.
   */
  instanceId?: string;
  /**
   * Optional remote runtime; passed through to runtimeConfigAtom on mount.
   */
  runtimeConfig?: { url: string; authToken?: string; lazy?: boolean; healthVerified?: boolean };
  /**
   * Sp-Server-Token header value.
   */
  serverToken?: string;
  /**
   * When false, setDocumentTitle() is a no-op. Embed clients default to false
   * so they don't stomp the host page's tab title. Standalone leaves the
   * client stack empty and setDocumentTitle defaults to true.
   */
  writeDocumentTitle?: boolean;
  /**
   * Host-controlled navigation. When set, the embed calls this instead of
   * mutating window.location for the three user-visible transitions:
   * notebook back-arrow, home-page card click, file-tree .py/.md/.qmd click.
   * Default: window.location.href = href.
   */
  navigate?: (href: string) => void;
}

/**
 * Opaque client value object. Carry it around to identify a mounted instance.
 */
export interface SignalpilotClient {
  readonly instanceId: string;
  readonly options: Readonly<SignalpilotClientOptions>;
  /** Per-client Jotai store. Bound to the proxy in SpEmbedProviders. */
  readonly store: JotaiStore;
  /** Per-client registries. Bound in SpEmbedProviders for the React tree's lifetime. */
  readonly registries: ClientRegistries;
  dispose(): void;
}

/**
 * Config shape accepted by `<SignalpilotEditor config={...}>`.
 * Deliberately omits `mode` — the embed components inject `"edit"` or `"home"`
 * into the options blob before passing to `initStore`.
 */
export interface SignalpilotMountConfig {
  filename?: string;
  initialCode?: string;
  /** Pre-fetched session snapshot (outputs). Threaded into mountOptionsSchema.session. */
  session?: unknown; // NotebookSessionV1 | null at runtime; mountOptionsSchema revalidates
  /** Pre-fetched notebook snapshot (structural metadata). Threaded into mountOptionsSchema.notebook. */
  notebook?: unknown; // NotebookV1 | null at runtime; mountOptionsSchema revalidates
  /**
   * Validated by the existing `parseUserConfig` in mount.tsx.
   * Accepts the raw userConfig object; unknown shape is intentional here.
   */
  userConfig?: unknown;
  appConfig?: unknown;
  configOverrides?: unknown;
  version?: string;
  serverToken?: string;
  runtimeConfig?: Array<{ url: string; authToken?: string; lazy?: boolean }>;
  gatewayUrl?: string;
  gatewayApiKey?: string;
}

export interface SignalpilotEditorProps {
  /** Required — the client this editor instance is bound to. */
  client: SignalpilotClient;
  /** Required — mount configuration. May be an empty object `{}`. */
  config: SignalpilotMountConfig;
  /** Optional CSS class applied to the `.sp-root` wrapper div. */
  className?: string;
}

export interface SignalpilotHomeProps {
  /** Required — the client this home instance is bound to. */
  client: SignalpilotClient;
  /**
   * No `config` prop — home page uses built-in theme defaults.
   * Home calls `initStore` with `mode: "home"` and an empty config blob,
   * which results in `passthroughObject`-defaulted atoms (`{}`). This is
   * acceptable because the home page reads `userConfig` for theme and the
   * default theme is fine. Documented as a Phase A limit.
   */
  className?: string;
}
