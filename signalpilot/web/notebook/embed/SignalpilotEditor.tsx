import { lazy, Suspense, useEffect, useRef } from "react";
import { forcedModeAtom, kioskModeAtom, viewerOnlyAtom } from "@/core/mode";
import { sessionIdAtom, type SessionId } from "@/core/kernel/session";
import { adaptMountConfig } from "./adaptMountConfig";
import { SpEmbedProviders } from "./SpEmbedProviders";
import type { SignalpilotEditorProps } from "./types";

const LazySpApp = lazy(() =>
  import("@/core/SpApp").then((module) => ({ default: module.SpApp })),
);

/**
 * Embeddable editor component.
 *
 * Renders the full SignalPilot editor (`mode: "edit"`) inside
 * `<SpEmbedProviders>`. The `mode` field is injected automatically — do not
 * include it in the `config` prop.
 *
 * The `.sp-root` wrapper scopes all rescoped CSS selectors to this subtree
 * so embed and host page styles don't bleed into each other. Theme classes
 * (`dark`/`light`, `dark-theme`/`light-theme`) are applied reactively by
 * `ThemeProvider` via `document.body`.
 *
 * Phase E: `SignalpilotEditorProps` will gain a `navigate` prop for host-
 * controlled routing. Today's embed inherits standalone navigation
 * (`window.location.href`).
 */
export function SignalpilotEditor({
  client,
  config,
  className,
  mode,
  kernelSessionId,
  readShowCode,
}: SignalpilotEditorProps): React.ReactElement {
  const options = adaptMountConfig({ config, client, mode: mode ?? "edit" });

  // Attach target for hosts connecting to an EXISTING kernel session (the
  // chat live notebook panel). sessionIdAtom's per-store initial value is
  // derived from the page URL's ?session_id — absent on non-notebook routes,
  // where it falls back to a RANDOM id and the websocket would silently
  // create a fresh empty session instead of attaching. Written on the
  // per-client store during render: idempotent, and it must be visible to
  // the first kernel-connection read.
  if (kernelSessionId) {
    client.store.set(sessionIdAtom, kernelSessionId as SessionId);
  }

  // Hosts that embed the editor on a non-notebook route (the chat page's
  // live notebook panel) have no ?file= in the page URL, so the URL-derived
  // mode would render the notebook HOME page. An explicit mode prop forces
  // the page choice. Only set when provided — the notebook surfaces keep
  // URL-derived navigation (e.g. dropping ?file= returns home).
  // Written on the per-client store during render: idempotent, and it must
  // be visible to SpApp's very first read.
  if (mode !== undefined) {
    client.store.set(forcedModeAtom, mode);
  }
  // Read-mode embeds are pure viewers: the rendered document must never be
  // replaced or washed out by connection-state chrome. The kiosk flag picks
  // the view: true renders code with outputs, false renders the traditional
  // outputs-only app view. The first write happens during render so the
  // first paint is correct; later toggles apply in an effect because a
  // changed atom value must not notify subscribers mid-render. viewerOnly
  // also stops kernel replays from overwriting the choice.
  const readInitializedRef = useRef(false);
  if (mode === "read" && !readInitializedRef.current) {
    readInitializedRef.current = true;
    client.store.set(viewerOnlyAtom, true);
    client.store.set(kioskModeAtom, readShowCode !== false);
  }
  useEffect(() => {
    if (mode === "read") {
      client.store.set(kioskModeAtom, readShowCode !== false);
    }
  }, [mode, readShowCode, client]);

  return (
    <div
      className={`sp-root relative h-full min-h-0 overflow-hidden${className ? ` ${className}` : ""}`}
    >
      <SpEmbedProviders client={client} options={options}>
        <Suspense fallback={null}>
          <LazySpApp />
        </Suspense>
      </SpEmbedProviders>
    </div>
  );
}
