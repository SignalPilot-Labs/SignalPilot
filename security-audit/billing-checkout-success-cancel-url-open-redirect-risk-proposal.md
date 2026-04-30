# `createCheckoutSession` forwards client-supplied `success_url`/`cancel_url` to backend without validation — open-redirect when paired with Stripe

- Slug: billing-checkout-success-cancel-url-open-redirect-risk
- Severity: Low
- Cloud impact: Yes
- Confidence: Medium (the gateway handler is not in this repo; the web client unconditionally forwards)
- Affected files / endpoints: `signalpilot/web/lib/backend-client.ts:278-292`, downstream `/api/v1/billing/checkout`

Back to [issues.md](issues.md)

---

## Problem

```ts
// lib/backend-client.ts:278-287
createCheckoutSession: (priceId: string, successUrl: string, cancelUrl: string) =>
  backendFetch<{ checkout_url: string | null; action: "checkout" | "updated" }>(
    "/api/v1/billing/checkout",
    getToken,
    {
      method: "POST",
      body: JSON.stringify({
        price_id: priceId,
        success_url: successUrl,
        cancel_url: cancelUrl,
      }),
    },
  ),
```

`successUrl` and `cancelUrl` arrive from the calling component and are forwarded as-is to the (out-of-repo) backend. Stripe's `Checkout.Session.create` accepts these URLs verbatim and uses them in the redirect after payment.

If the backend handler does not validate that the URLs are within the SignalPilot domain, an attacker who can phish a victim into clicking a crafted `signalpilot.ai/settings/billing?action=checkout&success_url=https://evil.example/...` link gets a Stripe-hosted page that, on completion, redirects to `evil.example`. Stripe's domain in the URL bar lends legitimacy to the lure.

The companion `createPortalSession(returnUrl)` (line 288-292) has the same shape with the same risk.

This is round-1 finding 52's cousin — that finding focused on the missing webhook handler. This one is about the redirect URLs flowing through the same code path.

---

## Impact

- Phishing leverage: attacker uses real `checkout.stripe.com` domain to redirect victims to attacker-controlled site after a "successful" payment, where they can be prompted to "complete" their account with credentials.
- Cookie / referrer leakage: SignalPilot session cookies on `*.signalpilot.ai` are not sent to `evil.example`, but the Stripe receipt URL may carry a `session_id` that can be used to fetch metadata.
- Reputation: `signalpilot.ai` becomes the launching point for attacks targeting customers' downstream tooling.

---

## Exploit scenario

1. Attacker crafts a deep link: `https://signalpilot.ai/settings/billing?upgrade=pro&success_url=https://evil.example/?stripe_done`.
2. The billing page reads the param and calls `createCheckoutSession(..., successUrl, cancelUrl)`.
3. Backend forwards verbatim to Stripe; checkout completes; Stripe redirects to `evil.example`.
4. Victim sees the URL change after Stripe and assumes the destination is legitimate.

---

## Affected surface

- Files: `signalpilot/web/lib/backend-client.ts:278-292`, `app/settings/billing/page.tsx`.
- Endpoints: `POST /api/v1/billing/checkout`, `POST /api/v1/billing/portal` (gateway side, not in repo).
- Auth modes: cloud (Clerk-authenticated user).

---

## Proposed fix

Two layers:

1. **Web client:** never accept `successUrl`/`cancelUrl` from URL search params. Compute these from a fixed table keyed on outcome, e.g. `successUrl = "${origin}/settings/billing?checkout=success"`.
2. **Backend (when implemented):** validate the URLs match `^https://(www\.)?signalpilot\.ai(/|$)` (or the configured tenant origin). Reject all other origins. Encode the validation as middleware shared with all `return_url`-style endpoints.

Document the constraint in the billing API contract.

---

## Verification / test plan

- Unit (web): `tests/lib/billing-urls.test.ts::test_success_url_is_origin-only`.
- Unit (gateway): once handler exists, `tests/test_billing_checkout.py::test_rejects_external_success_url`.
- Manual: craft a request with `success_url=https://example.com`; expect 400.

---

## Rollout / migration notes

- No customer-visible change for legitimate flows.
- Rollback: relax validation; non-destructive.
