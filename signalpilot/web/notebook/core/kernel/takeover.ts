import { Logger } from "@/utils/Logger";
import {
  isNotionTrailSearchParams,
  sanitizeNotionTrailSearchParams,
} from "../notion/trail";

/**
 * POST to /api/kernel/takeover to disconnect any stale WebSocket session
 * and reclaim the kernel. Throws on network failure — callers decide retry.
 */
export async function takeoverKernel(
  runtimeUrl: string,
  headers: Record<string, string>,
): Promise<void> {
  const currentParams = new URLSearchParams(window.location.search);
  const searchParams = isNotionTrailSearchParams(currentParams)
    ? sanitizeNotionTrailSearchParams(currentParams)
    : currentParams;
  const url = `${runtimeUrl}/api/kernel/takeover?${searchParams.toString()}`;

  Logger.debug("Taking over kernel session", { url });

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: "{}",
  });

  if (!resp.ok) {
    throw new Error(`Takeover failed: ${resp.status} ${resp.statusText}`);
  }
}
