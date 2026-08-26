import { initializeUIElement } from "../core/dom/ui-element";
import { initializeSidebarElement } from "./core/sidebar-element";

/**
 * Initialize only the custom DOM element registrations (sp-ui-element and
 * sp-sidebar). This is the lightweight entry-graph variant — it has ZERO
 * imports from plugins-react.ts so no plugin class ends up in the home
 * critical-path chunk.
 *
 * Use initializePlugins() from plugins-react.ts when you also need the full
 * React plugin registry (edit / read / islands modes).
 */
export function initializeCustomElements(): void {
  initializeUIElement();
  initializeSidebarElement();
}
