import { SpApp } from "@/core/SpApp";
import { adaptMountConfig } from "./adaptMountConfig";
import { SpEmbedProviders } from "./SpEmbedProviders";
import type { SignalpilotEditorProps } from "./types";

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
}: SignalpilotEditorProps): React.ReactElement {
  const options = adaptMountConfig({ config, client, mode: "edit" });

  return (
    <div
      className={`sp-root${className ? ` ${className}` : ""}`}
    >
      <SpEmbedProviders client={client} options={options}>
        <SpApp />
      </SpEmbedProviders>
    </div>
  );
}
