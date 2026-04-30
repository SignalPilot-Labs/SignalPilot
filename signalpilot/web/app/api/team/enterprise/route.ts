import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

/**
 * Enterprise SSO connections API route.
 * Requires Clerk paid plan — stubbed out for now.
 * Protected by Clerk auth: requires authenticated org admin.
 */

export interface EnterpriseConnectionDTO {
  id: string;
  name: string;
  protocol: "saml" | "oidc" | "unknown";
  domains: string[];
  active: boolean;
  createdAt: number;
  updatedAt: number;
  saml: {
    acsUrl: string | null;
    spEntityId: string | null;
    spMetadataUrl: string | null;
    idpEntityId: string | null;
    idpSsoUrl: string | null;
  } | null;
  oidc: {
    clientId: string | null;
    discoveryUrl: string | null;
  } | null;
}

export async function GET() {
  const { userId, orgId, orgRole } = await auth();
  if (!userId || !orgId) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }
  if (orgRole !== "org:admin") {
    return NextResponse.json({ error: "Admin role required" }, { status: 403 });
  }
  // Enterprise SSO requires Clerk paid plan — return empty list
  return NextResponse.json({ connections: [] });
}
