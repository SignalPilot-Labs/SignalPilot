# No Clerk webhook handler — user/org lifecycle drift between Clerk and gateway

- Slug: no-clerk-webhook-signature-verification-handler
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: Entire repo (no `app/api/webhooks/clerk` route exists); `signalpilot/gateway/gateway/store.py` API key table; `signalpilot/web/`

Back to [issues.md](issues.md)

---

## Problem

There is no Clerk webhook receiver in the codebase. Clerk emits lifecycle events (`organization.deleted`, `user.deleted`, `organizationMembership.deleted`, `session.removed`) that must be consumed to keep gateway state synchronized with Clerk's source of truth.

The gateway derives `org_id` and `user_id` from JWT claims at request time. This is correct for in-flight requests. However:

1. **API keys minted while a user was a valid org member persist after that membership is revoked.** API keys store `org_id` and `user_id` at creation time. When a user leaves an org in Clerk, their Clerk session token cannot be used (Clerk stops issuing org-scoped tokens), but any gateway API key they created continues to authenticate as that org indefinitely — there is no revocation path.

2. **When an org is deleted in Clerk, all resources for that org remain in the gateway DB.** Connections, BYOK keys, encrypted credentials, and audit history for `org_id=<deleted-org>` are never cleaned up.

3. **There is no idempotency mechanism** for webhook delivery (Clerk may re-deliver on failure). Without a webhook ID store, duplicate events could trigger duplicate deletes or race conditions.

The `standardwebhooks` package is already present in `package-lock.json` (the Svix standard library for webhook signature verification), indicating this was planned but not implemented.

---

## Impact

- **Indefinite API key validity after membership revocation.** A fired employee or a compromised contractor account can continue to issue queries against the organization's data warehouses using a previously minted API key.
- **Data retention risk.** Deleted orgs' encrypted credentials remain in the database indefinitely — a GDPR/CCPA compliance risk.
- **Audit log pollution.** Requests from revoked users continue to generate audit log entries attributed to a valid org, creating forensic confusion.

---

## Exploit scenario

1. Employee `alice@acme.com` is a member of org `acme` and creates a SignalPilot API key `sp_abc123...`.
2. Alice leaves ACME; her Clerk membership is revoked by the org admin.
3. Alice's Clerk JWT is no longer issuable for the `acme` org.
4. Alice uses her previously saved API key: `curl https://gateway.signalpilot.ai/mcp -H "X-API-Key: sp_abc123..."`.
5. Gateway validates the key hash against the DB — it still exists with `org_id=acme` — and grants access to all ACME connections and data.
6. Alice can read ACME's warehouse data indefinitely.

---

## Affected surface

- Files: None (the route does not exist); needs creation at `signalpilot/web/app/api/webhooks/clerk/route.ts`
- Endpoints: `POST /api/webhooks/clerk` (to be created)
- Auth modes: Webhook signature verification replaces JWT auth for this endpoint

---

## Proposed fix

Create `signalpilot/web/app/api/webhooks/clerk/route.ts`:

```typescript
import { Webhook } from "standardwebhooks";
import { NextRequest, NextResponse } from "next/server";

const WEBHOOK_SECRET = process.env.CLERK_WEBHOOK_SECRET;

export async function POST(req: NextRequest) {
  if (!WEBHOOK_SECRET) {
    return NextResponse.json({ error: "Webhook not configured" }, { status: 500 });
  }

  const wh = new Webhook(WEBHOOK_SECRET);
  const body = await req.text();
  const headers = {
    "webhook-id": req.headers.get("svix-id") ?? "",
    "webhook-timestamp": req.headers.get("svix-timestamp") ?? "",
    "webhook-signature": req.headers.get("svix-signature") ?? "",
  };

  let event: ClerkWebhookEvent;
  try {
    event = wh.verify(body, headers) as ClerkWebhookEvent;
  } catch {
    return NextResponse.json({ error: "Invalid signature" }, { status: 401 });
  }

  // Idempotency: store svix-id in DB, skip if already processed
  const svixId = req.headers.get("svix-id");
  // ... check DB for processed svixId ...

  switch (event.type) {
    case "organizationMembership.deleted":
      await revokeKeysForUserInOrg(event.data.public_user_data.user_id, event.data.organization.id);
      break;
    case "user.deleted":
      await revokeAllKeysForUser(event.data.id);
      break;
    case "organization.deleted":
      await revokeAllKeysForOrg(event.data.id);
      // optionally delete all org data
      break;
  }

  return NextResponse.json({ received: true });
}
```

On the gateway side, add a revocation endpoint `DELETE /api/v1/keys/revoke-by-org` and `revoke-by-user` callable from the web tier (with a shared internal secret).

---

## Verification / test plan

**Unit tests:**
1. `test_webhook_invalid_signature_returns_401` — send request with wrong signature.
2. `test_webhook_membership_deleted_revokes_keys` — mock `organizationMembership.deleted`, verify API keys for that user+org are deleted.
3. `test_webhook_idempotent` — send same svix-id twice, verify keys deleted only once.

**Manual checklist:**
- Configure Clerk webhook pointing to `https://signalpilot.ai/api/webhooks/clerk`.
- Remove a member from an org in Clerk dashboard.
- Verify the webhook fires and the member's API keys are deleted in the gateway DB.
- Attempt to use the deleted key — expect 401.

---

## Rollout / migration notes

- **Order of operations:**
  1. Deploy `route.ts` with `CLERK_WEBHOOK_SECRET` set.
  2. Configure Clerk webhook endpoint in the Clerk dashboard.
  3. Test with a non-production org.
- **Customer-visible impact:** None for legitimate users. Revoked users' keys stop working immediately after membership revocation instead of after expiry.
- **Rollback:** Remove the Clerk webhook configuration in the Clerk dashboard; the endpoint can remain deployed safely.
