import { atom } from "jotai";
import { BUILD_ENV } from "./build-env";

const BUILD_VERSION: string = BUILD_ENV.SP_VERSION;

export const spVersionAtom = atom<string>(BUILD_VERSION);

export const showCodeInRunModeAtom = atom<boolean>(true);

export const serverTokenAtom = atom<string | null>(null);

/**
 * True when the backend opened a non-notebook file in raw-editor fallback mode.
 * Set by `initStore` from the mount-config response. When true, the kernel
 * WebSocket is not opened and the file is rendered by the raw file editor.
 */
export const rawFallbackAtom = atom<boolean>(false);

/**
 * Base URL for the SignalPilot data gateway API (SP_GATEWAY_URL env var on
 * the backend). Falls back to localhost:3300 for local dev when not set.
 */
export const gatewayUrlAtom = atom<string>("http://localhost:3300");

/**
 * API key for the SignalPilot gateway (SP_SESSION_JWT or SP_API_KEY on the
 * backend). Empty string when not configured.
 */
export const gatewayApiKeyAtom = atom<string>("");
