import { NextResponse } from "next/server";

const IS_CLOUD = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
const GATEWAY_URL = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3300";

let _cachedKey: string | null = null;

/**
 * Server-side API route that returns the local API key.
 *
 * Resolution order:
 * 1. SP_LOCAL_API_KEY env var (Docker entrypoint)
 * 2. Fetch from gateway's /local-api-key endpoint (pnpm dev)
 * 3. null
 */
export async function GET() {
  if (IS_CLOUD) {
    return NextResponse.json({ error: "Not available in cloud mode" }, { status: 404 });
  }

  const envKey = process.env.SP_LOCAL_API_KEY;
  if (envKey) {
    return NextResponse.json({ key: envKey });
  }

  if (!_cachedKey) {
    try {
      const resp = await fetch(`${GATEWAY_URL}/local-api-key`, {
        signal: AbortSignal.timeout(3000),
      });
      if (resp.ok) {
        const data = await resp.json();
        _cachedKey = data.key ?? null;
      }
    } catch {
      // Gateway unreachable
    }
  }

  return NextResponse.json({ key: _cachedKey ?? null });
}
