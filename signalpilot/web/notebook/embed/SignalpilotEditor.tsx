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
 * The `.sp-root.dark.dark-theme` wrapper scopes all rescoped CSS selectors
 * to this subtree so embed and host page styles don't bleed into each other.
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
      className={`sp-root dark dark-theme${className ? ` ${className}` : ""}`}
      data-theme="dark"
    >
      <SpEmbedProviders client={client} options={options}>
        <SpApp />
      </SpEmbedProviders>
    </div>
  );
}
