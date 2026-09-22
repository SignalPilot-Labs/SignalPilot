import type { McpUiHostContext } from "@modelcontextprotocol/ext-apps";

/**
 * Host context → document attributes. The panel keeps the SignalPilot ink
 * palette and fonts on every host, so host style variables and theme are
 * deliberately not applied; display mode, safe-area insets and locale are.
 */
export function applyHostContext(context: McpUiHostContext | undefined, root: HTMLElement = document.documentElement) {
  if (!context) return;
  if (context.theme) root.dataset.hostTheme = context.theme;
  if (context.displayMode) root.dataset.displayMode = context.displayMode;
  const insets = context.safeAreaInsets;
  if (insets) {
    root.style.setProperty("--sp-safe-top", `${insets.top}px`);
    root.style.setProperty("--sp-safe-right", `${insets.right}px`);
    root.style.setProperty("--sp-safe-bottom", `${insets.bottom}px`);
    root.style.setProperty("--sp-safe-left", `${insets.left}px`);
  }
  if (context.locale) root.lang = context.locale;
}
