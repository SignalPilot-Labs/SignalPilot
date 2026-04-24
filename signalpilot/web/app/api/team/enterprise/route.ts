import { auth, clerkClient } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

/**
 * DTO shape returned to the client. Co-located here so the route constructs
 * it explicitly — no spread of the full Clerk resource.
 *
 * Exported so team-enterprise-section.tsx can import the type for its state.
 * clientSecret and idpCertificate are intentionally excluded.
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

  if (!userId) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (!orgId) {
    return NextResponse.json({ error: "no active organization" }, { status: 400 });
  }
  if (orgRole !== "org:admin") {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  const client = await clerkClient();
  const list = await client.enterpriseConnections.getEnterpriseConnectionList({
    organizationId: orgId,
  });

  // Defensive: filter on organizationId — never trust the SDK param alone
  // for tenant isolation. Whitelist fields explicitly; never spread connection.
  const connections: EnterpriseConnectionDTO[] = list.data
    .filter((c) => c.organizationId === orgId)
    .map((c) => ({
      id: c.id,
      name: c.name,
      protocol: c.samlConnection ? "saml" : c.oauthConfig ? "oidc" : "unknown",
      domains: c.domains,
      active: c.active,
      createdAt: c.createdAt,
      updatedAt: c.updatedAt,
      saml: c.samlConnection
        ? {
            acsUrl: c.samlConnection.acsUrl ?? null,
            spEntityId: c.samlConnection.spEntityId ?? null,
            spMetadataUrl: c.samlConnection.spMetadataUrl ?? null,
            idpEntityId: c.samlConnection.idpEntityId ?? null,
            idpSsoUrl: c.samlConnection.idpSsoUrl ?? null,
          }
        : null,
      oidc: c.oauthConfig
        ? {
            clientId: c.oauthConfig.clientId ?? null,
            discoveryUrl: c.oauthConfig.discoveryUrl ?? null,
          }
        : null,
    }));

  return NextResponse.json({ connections });
}
