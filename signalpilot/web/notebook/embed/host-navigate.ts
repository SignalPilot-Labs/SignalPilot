import { getCurrentClient } from "@/embed/client-binding";
import { spaNavigate } from "@/core/router/spa-navigate";

/**
 * Navigate to href. Embed mode: delegates to the host router.
 * Standalone: in-page SPA navigation via history.pushState.
 * Never reloads the document.
 */
export function navigate(href: string): void {
  if (!href) throw new Error("navigate: empty href");
  const hostNavigate = getCurrentClient()?.options.navigate;
  if (hostNavigate !== undefined) {
    hostNavigate(href);
    return;
  }
  spaNavigate(href);
}
