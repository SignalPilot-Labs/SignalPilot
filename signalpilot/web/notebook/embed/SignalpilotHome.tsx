import { SpApp } from "@/core/SpApp";
import { adaptMountConfig } from "./adaptMountConfig";
import { SpEmbedProviders } from "./SpEmbedProviders";
import type { SignalpilotHomeProps } from "./types";

/**
 * Embeddable home-page component.
 *
 * Renders the SignalPilot home page (`mode: "home"`) inside
 * `<SpEmbedProviders>`. Home page uses built-in theme defaults — there is no
 * `config` prop because `initStore` will receive `mode: "home"` with an
 * otherwise empty blob.
 *
 * The `.sp-root.dark.dark-theme` wrapper scopes all rescoped CSS selectors
 * to this subtree so embed and host page styles don't bleed into each other.
 */
export function SignalpilotHome({
  client,
  className,
}: SignalpilotHomeProps): React.ReactElement {
  const options = adaptMountConfig({
    config: {},
    client,
    mode: "home",
  });

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
