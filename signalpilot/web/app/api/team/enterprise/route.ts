import { NextResponse } from "next/server";

/**
 * Enterprise SSO connections API route.
 * Requires Clerk paid plan — stubbed out for now.
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
  // Enterprise SSO requires Clerk paid plan — return empty list
  return NextResponse.json({ connections: [] });
}
