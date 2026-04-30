# `GET /api/team/enterprise` is a stub that always returns empty list

- Slug: enterprise-sso-route-stub-returns-empty
- Severity: Info
- Cloud impact: No
- Confidence: High
- Affected files / endpoints: `signalpilot/web/app/api/team/enterprise/route.ts:29-31`

Back to [issues.md](issues.md)

---

## Problem

The enterprise SSO route handler always returns an empty list with no authentication check:

```typescript
// app/api/team/enterprise/route.ts:29-31
export async function GET() {
  // Enterprise SSO requires Clerk paid plan — return empty list
  return NextResponse.json({ connections: [] });
}
```

The file contains a well-designed `EnterpriseConnectionDTO` interface (lines 8-27), indicating the implementation was planned. The companion document `enterprise-connections.md` describes the intended behavior: enforce `org:admin` role, call the Clerk Backend SDK with an org-scoped filter, and apply a `organizationId === orgId` defensive check on returned data.

The current stub is not a security vulnerability *today* because it returns no data. However:
1. The code does not match the documented behavior, creating a false sense of security for anyone reading the docs.
2. A future developer implementing the handler without reading this stub closely may omit the `org:admin` check, trusting that the pattern in the file represents the intended security model.
3. The route responds 200 to any caller (authenticated or not), which leaks the existence of the enterprise endpoint.

---

## Impact

- No current exploitability (returns empty list).
- Risk is technical debt: the security requirement is documented but not enforced in code, creating a "compliance debt" that is likely to be skipped when the feature is fully implemented.

---

## Exploit scenario

Not currently exploitable. Future risk if implemented without auth:

```bash
curl https://signalpilot.ai/api/team/enterprise
# Returns: {"connections":[]} — 200 with no auth required
# After full implementation without auth fix: returns SSO configs for all orgs
```

---

## Affected surface

- Files: `signalpilot/web/app/api/team/enterprise/route.ts:29-31`
- Endpoints: `GET /api/team/enterprise`
- Auth modes: Unauthenticated (currently harmless; dangerous when implemented)

---

## Proposed fix

Either implement the endpoint correctly now, or return a clear error:

**Option A — stub with proper auth gate:**
```typescript
import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

export async function GET() {
  const { has, orgId } = auth();
  if (!orgId) {
    return NextResponse.json({ error: "Not signed in" }, { status: 401 });
  }
  if (!has({ role: "org:admin" })) {
    return NextResponse.json({ error: "Requires org:admin role" }, { status: 403 });
  }
  // TODO: implement Clerk Backend SDK call
  return NextResponse.json({ connections: [], _note: "Not yet implemented" });
}
```

**Option B — remove route until implemented:**
Delete the file and return 404. Document in the codebase that the endpoint is planned.

---

## Verification / test plan

**Tests:**
1. `test_enterprise_route_unauthenticated_returns_401` — no session cookie, assert 401.
2. `test_enterprise_route_non_admin_returns_403` — regular org member, assert 403.
3. `test_enterprise_route_admin_returns_200` — org admin, assert 200.

---

## Rollout / migration notes

- No data migration.
- No customer-visible impact if option A is chosen (returns same empty list, now with auth).
- If option B, any frontend component consuming this endpoint will need to handle 404.
