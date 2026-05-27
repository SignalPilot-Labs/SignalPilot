/**
 * @signalpilot/embed — public embed surface.
 *
 * Only items explicitly listed here are part of the public contract.
 * Keep this file auditable: every export should have a clear reason to exist.
 *
 * Phase D (this build): style.css is now host-safe — all global selectors
 * (`:root`, `html`, `body`) are rescoped to `.sp-root` via PostCSS. Two
 * embeds with different themes on the same page are mechanically possible;
 * the per-instance theme API ships in Phase E.
 */

export { SignalpilotEditor } from "./SignalpilotEditor";
export { SignalpilotHome } from "./SignalpilotHome";
export { SpEmbedProviders } from "./SpEmbedProviders";
export { createSignalpilotClient } from "./createSignalpilotClient";
export type {
  SignalpilotClient,
  SignalpilotClientOptions,
  SignalpilotEditorProps,
  SignalpilotHomeProps,
  SignalpilotMountConfig,
} from "./types";
