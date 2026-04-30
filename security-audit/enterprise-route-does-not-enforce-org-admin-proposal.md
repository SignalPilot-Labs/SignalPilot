# `app/api/team/enterprise/route.ts` GET has no Clerk auth check at all

- Slug: enterprise-route-does-not-enforce-org-admin
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/web/app/api/team/enterprise/route.ts:29`

Back to [issues.md](issues.md)

---

## Problem

This is related to finding [enterprise-sso-route-stub-returns-empty](enterprise-sso-route-stub-returns-empty-proposal.md) but focuses specifically on the missing authorization enforcement pattern.

The `GET` handler has no Clerk auth check:

```typescript
// app/api/team/enterprise/route.ts:29-31
export async function GET() {
  return NextResponse.json({ connections: [] });
}
```

The companion document `enterprise-connections.md` specifies:
- Must require `org:admin` role.
- Must use Clerk Backend SDK with org-scoped filter.
- Must apply `organizationId === orgId` defensive filter.

None of this is implemented. The route returns 200 to any caller, authenticated or not.

When this route is fully implemented (as it eventually must be, per the DTO interface already defined in the file), there is a risk that the implementer copies the stub pattern without adding the auth check. Codifying the auth requirement now, in code (not just docs), prevents this.

---

## Impact

- Currently: no sensitive data exposed (empty list).
- After full implementation without auth check: SSO enterprise connections exposed to any unauthenticated caller.
- Precedent risk: the current stub normalizes the "no auth" pattern for this endpoint.

---

## Affected surface

- Files: `signalpilot/web/app/api/team/enterprise/route.ts:29-31`
- Endpoints: `GET /api/team/enterprise`
- Auth modes: Unauthenticated (currently); should require `org:admin`

---

## Proposed fix

Add auth check immediately, even on the stub, to establish the correct pattern:

```typescript
// app/api/team/enterprise/route.ts:
import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

export async function GET() {
  const { has, orgId } = auth();

  if (!orgId) {
    return NextResponse.json({ error: "Authentication required" }, { status: 401 });
  }

  if (!has({ role: "org:admin" })) {
    return NextResponse.json(
      { error: "This endpoint requires org:admin role" },
      { status: 403 }
    );
  }

  // TODO: implement Clerk Backend SDK call to fetch enterprise SSO connections
  // Requires Clerk paid plan (Enterprise tier)
  return NextResponse.json({ connections: [] });
}
```

This ensures that when the full implementation is added, the auth check is already in place and cannot be accidentally omitted.

---

## Verification / test plan

**Unit tests:**
1. `test_enterprise_route_no_auth_401` — no session, assert 401.
2. `test_enterprise_route_non_admin_403` — authenticated regular member, assert 403.
3. `test_enterprise_route_admin_200` — org:admin, assert 200 with empty list.

---

## Rollout / migration notes

- No data migration.
- No customer-visible change (endpoint still returns empty list, now with auth required).
- Rollback: remove auth check (not recommended).

**Related findings:** [enterprise-sso-route-stub-returns-empty](enterprise-sso-route-stub-returns-empty-proposal.md)
