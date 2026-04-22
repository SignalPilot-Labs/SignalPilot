import { NextResponse } from "next/server";

/**
 * Server-side API route that returns the local API key.
 * The key is injected at container startup from the shared volume.
 * Only accessible from the same browser origin (same-origin policy).
 */
export async function GET() {
  const key = process.env.SP_LOCAL_API_KEY;
  if (!key) {
    return NextResponse.json({ key: null });
  }
  return NextResponse.json({ key });
}
