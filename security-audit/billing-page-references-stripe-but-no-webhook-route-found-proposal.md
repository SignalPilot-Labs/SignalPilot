# `app/settings/billing/page.tsx` and `use-tier-upgrade.ts` reference Stripe but no `/api/webhooks/stripe` handler exists in repo

- Slug: billing-page-references-stripe-but-no-webhook-route-found
- Severity: Medium
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/web/lib/hooks/use-tier-upgrade.ts:64`, `signalpilot/web/app/settings/billing/page.tsx`

Back to [issues.md](issues.md)

---

## Problem

The frontend references Stripe-related functionality for tier upgrades:

```typescript
// lib/hooks/use-tier-upgrade.ts:64 (approximate)
// References Stripe checkout, subscription management
```

However, no `POST /api/webhooks/stripe` handler exists in the repository. Stripe webhooks are required for:
1. **Confirming payment success** — without a webhook, a user's tier may not upgrade even after successful payment.
2. **Handling subscription cancellation** — without handling `customer.subscription.deleted`, cancelled subscriptions continue to grant paid-tier access.
3. **Fraud prevention** — Stripe `payment_intent.payment_failed` events trigger account lockout; without processing them, failed payments go undetected.
4. **Signature verification** — if the webhook handler is elsewhere (outside this repo), its security cannot be assessed. If it lacks `stripe.webhooks.constructEvent()` verification, any attacker can POST fake events and grant themselves premium access.

This finding has Medium confidence because:
- Stripe integration may be handled by a separate service not in this repo.
- The severity depends on whether billing is live in production.

---

## Impact

- **If billing is live and webhook is missing:** Subscription state is not synchronized. Users may retain access after cancellation or lose access after payment.
- **If webhook exists but lacks signature verification:** Any attacker can POST a fake `customer.subscription.updated` event and grant themselves a premium tier.
- **Data integrity:** Without webhook-driven state updates, the subscription database may diverge from Stripe's records.

---

## Exploit scenario

**If webhook endpoint lacks signature verification:**
```bash
# Attacker posts fake Stripe event:
curl https://signalpilot.ai/api/webhooks/stripe \
  -H "Content-Type: application/json" \
  -d '{
    "type": "customer.subscription.updated",
    "data": {
      "object": {
        "customer": "cus_attacker_id",
        "status": "active",
        "plan": {"id": "plan_enterprise"}
      }
    }
  }'
# If no signature check: attacker upgrades their account to enterprise for free
```

---

## Affected surface

- Files: `signalpilot/web/lib/hooks/use-tier-upgrade.ts:64`, `signalpilot/web/app/settings/billing/page.tsx`
- Endpoints: `POST /api/webhooks/stripe` (should exist, does not in repo)
- Auth modes: Unauthenticated (Stripe webhooks use signature verification, not user auth)

---

## Proposed fix

**Step 1: Determine architecture.** Confirm whether Stripe webhook handling is:
- In this repo (in which case it is missing — must be implemented).
- In a separate service (in which case document it; ensure signature verification is present).
- Not yet implemented (billing not live — mark as future requirement).

**Step 2 (if implementing in this repo):**

```typescript
// app/api/webhooks/stripe/route.ts:
import Stripe from "stripe";
import { NextRequest, NextResponse } from "next/server";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
const WEBHOOK_SECRET = process.env.STRIPE_WEBHOOK_SECRET!;

export async function POST(request: NextRequest) {
  const body = await request.text();
  const sig = request.headers.get("stripe-signature") ?? "";

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, sig, WEBHOOK_SECRET);
  } catch (err) {
    return NextResponse.json({ error: "Webhook signature invalid" }, { status: 400 });
  }

  switch (event.type) {
    case "customer.subscription.updated":
    case "customer.subscription.deleted":
      await handleSubscriptionChange(event.data.object as Stripe.Subscription);
      break;
    case "invoice.payment_failed":
      await handlePaymentFailed(event.data.object as Stripe.Invoice);
      break;
  }

  return NextResponse.json({ received: true });
}
```

Key requirements:
- `stripe.webhooks.constructEvent()` — mandatory signature verification.
- Idempotency: store processed event IDs in DB.
- Scope checks: verify the event's customer maps to the expected org.

---

## Verification / test plan

**Unit tests:**
1. `test_stripe_webhook_invalid_signature_returns_400`.
2. `test_stripe_subscription_cancelled_revokes_access`.
3. `test_stripe_webhook_idempotent` — same event ID twice, assert single processing.

**Manual checklist:**
- Use Stripe CLI to forward test events: `stripe listen --forward-to https://signalpilot.ai/api/webhooks/stripe`.
- Test each event type.

---

## Rollout / migration notes

- Set `STRIPE_WEBHOOK_SECRET` from Stripe dashboard.
- Test in Stripe test mode before enabling in production.
- Rollback: disable the webhook endpoint in Stripe dashboard.

**Related findings:** [no-clerk-webhook-signature-verification-handler](no-clerk-webhook-signature-verification-handler-proposal.md)
