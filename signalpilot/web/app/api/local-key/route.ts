import { NextResponse } from "next/server";

const IS_CLOUD = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";

/**
 * Server-side API route that returns the local API key.
 * The key is injected at container startup from the shared volume.
 * Only accessible from the same browser origin (same-origin policy).
 * Disabled in cloud mode to prevent key exposure.
 */
export async function GET() {
  if (IS_CLOUD) {
    return NextResponse.json({ error: "Not available in cloud mode" }, { status: 404 });
  }
  const key = process.env.SP_LOCAL_API_KEY;
  if (!key) {
    return NextResponse.json({ key: null });
  }
  return NextResponse.json({ key });
}
