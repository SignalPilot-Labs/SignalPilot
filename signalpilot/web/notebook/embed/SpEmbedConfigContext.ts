import { createContext, useContext } from "react";
import type { SignalpilotClient } from "./types";

/**
 * Context that carries the active `SignalpilotClient` through the embed tree.
 *
 * Lives in its own file so Phase B can swap the value to a store-bearing
 * client (adding `store`, `requestClient`, etc.) without touching component
 * files that consume this hook.
 *
 * Set by `<SpEmbedProviders client={...}>`.
 * Consumed via `useSpEmbedClient()`.
 */
export const SpEmbedConfigContext =
  createContext<SignalpilotClient | null>(null);

/**
 * Returns the active `SignalpilotClient`.
 *
 * Throws if called outside of `<SpEmbedProviders>` — this is intentional.
 * Fail-fast: do not add a fallback default here.
 */
export function useSpEmbedClient(): SignalpilotClient {
  const client = useContext(SpEmbedConfigContext);
  if (client === null) {
    throw new Error(
      "useSpEmbedClient must be called inside <SpEmbedProviders>. " +
        "Did you forget to wrap your component?",
    );
  }
  return client;
}
