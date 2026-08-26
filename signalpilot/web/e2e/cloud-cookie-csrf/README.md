# Real-browser cloud-mode cookie auth + CSRF suite

Every other cloud-mode E2E test in this repo authenticates with
`Authorization: Bearer`. `CookieAuthCsrfMiddleware` **explicitly exempts** Bearer
callers (`csrf.py` step 3), so the path a real browser actually uses — a Clerk
`__session` cookie with `Origin` / `Sec-Fetch-Site` set by the browser itself — had
no coverage at all. This suite closes that gap with a real Chromium instance.

## Running it

```bash
cd signalpilot/gateway
python -m tests.e2e_cloud.browser_driver
```

The Python driver is the entry point; it boots everything, then invokes Playwright.
Runtime is roughly 60 seconds end to end (~20 s of it in the browser).

```bash
# baseline mode: report the suite result but always exit 0
python -m tests.e2e_cloud.browser_driver --baseline

# the spec on its own — SKIPS cleanly, since nothing is provisioned
cd signalpilot/web && npx playwright test e2e/cloud-cookie-csrf/
```

### What the driver does

1. Provisions a throwaway Clerk organisation with a real `org:admin` and a real
   `org:member`, reusing `tests/e2e_cloud/clerk_backend.py` (2 users, 1 org, 2
   sessions), and sweeps residue from any interrupted previous run.
2. Drops and recreates the throwaway Postgres database `sp_e2e_browser` inside the
   **existing** dev container `signalpilot-db-1`. It never touches the `signalpilot`
   database.
3. Boots `uvicorn gateway.main:app` with `SP_DEPLOYMENT_MODE=cloud` on port 3397
   (falling back to an ephemeral port), pinned to the `unlimited` plan tier so plan
   gating cannot masquerade as an authorization denial.
4. Seeds a connection whose password is a random canary string, and **proves an
   authorized admin can exfiltrate it over Bearer** — otherwise every negative
   exfiltration assertion in the suite would be vacuous.
5. Discovers every admin-gated route from the live FastAPI dependency tree
   (`tests/e2e_cloud/routes.py`) — 53 at the time of writing — and hands the list to
   the browser suite.
6. Runs the Playwright spec, then deletes the connection, stops the gateway, and
   deletes every Clerk resource it created.

### Prerequisites

| Requirement | If missing |
| --- | --- |
| `docker` CLI + `signalpilot-db-1` running on 127.0.0.1:5601 | driver exits 2, suite never runs |
| `CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY` in the repo-root `.env` (test tier only) | driver exits 2 |
| outbound network to `api.clerk.com` | driver exits 2 |
| `npx` + `@playwright/test` + chromium in `signalpilot/web/node_modules` | driver exits 2 |

The spec itself is guarded by a file-level `test.skip`, so running the web E2E
directory in CI without any of the above marks these tests **skipped, never failed**.

Ports used: gateway **3397**, attacker origin **4501** (both auto-fall-back to an
ephemeral port if occupied). Nothing on 3300 / 3200 / 2718 / 3398 / 3399 is touched.

## Origin topology — this is load-bearing

```
gateway   http://localhost:3397    <- also the sole entry in SP_ALLOWED_ORIGINS
attacker  http://127.0.0.1:4501    <- a DIFFERENT SITE
```

* `gateway/main.py::_build_allowed_origins` keeps a cloud-mode origin only if it is
  `https://` or starts with `http://localhost`, so a `http://127.0.0.1:<port>` entry
  would be silently dropped. Hence the gateway is *addressed* as `localhost`.
* Two **ports** on the same host would be **same-site**, not cross-site: ports are
  not part of a site. Such a request legitimately passes `csrf.py` step 4. The
  attacker therefore lives on a different host (`127.0.0.1` vs `localhost`), which is
  what makes Chromium emit `Sec-Fetch-Site: cross-site`.

## What is genuinely reachable from a browser

Worth understanding before reading the assertions, because it determines which
routes the CSRF middleware is actually protecting:

| Cross-site attempt | Reaches the handler? | Blocked by |
| --- | --- | --- |
| `PUT` / `PATCH` / `DELETE` via `fetch` | **no** | CORS preflight — the browser never sends it |
| `POST` with `application/json` via `fetch` | **no** | CORS preflight |
| `POST` with `text/plain` via `fetch` | yes, request is sent | **CSRF middleware (403)** |
| HTML form auto-submit (`urlencoded` / `multipart` / `text/plain`) | yes, request is sent | **CSRF middleware (403)** |
| `GET` (safe method) | yes | nothing — CORS only hides the *response* |

So for JSON-body routes CSRF is doubly defended, and the middleware is the *only*
defence for POST routes that need no JSON body (query-parameter POSTs such as
`/api/cache/invalidate`, `/api/schema-cache/invalidate`, and multipart upload
routes). Those are the routes this suite attacks.

## Coverage

| Test | Asserts |
| --- | --- |
| cookie sanity | the injected `__session` cookie really authenticates (guards against every assertion below being vacuous) |
| A1 | cross-site form POST + valid cookie -> **403**, browser-set `Sec-Fetch-Site: cross-site` and `Origin: <attacker>`, cookie really sent, no `Authorization` header, handler did not run |
| A2 | the **same** form POST from the gateway origin -> **200** and the handler ran. A1's 403 is therefore attributable to CSRF, not to validation or authorization |
| A3 | cross-site form POST to `POST /api/connections/export` `{include_credentials, confirm}` -> **403**, body is exactly the CSRF body, canary absent |
| A4 | identical form shape: **403** cross-site vs **422** same-origin — CSRF fires *before* body parsing |
| A5 | blind cross-site `fetch` with `text/plain` (no preflight): the server answers **403** (read from the access log) and the attacker's JS cannot read the response |
| A6 | cross-site `PUT /api/settings`: never reaches the server at all (no `PUT` in the access log), and `default_row_limit` is unchanged when read back |
| A7 | defence in depth — a `SameSite=Lax` `__session` cookie is not even *sent* cross-site, so the request arrives unauthenticated |
| B1 | same-origin cookie `PUT /api/settings` by an admin is **not** 401/403, is 200, and the change is visible on read-back (then restored) |
| B2 | same-origin cookie POST by an admin is never 401/403 |
| C | **all 53** discovered admin-gated routes x {cookie member, cookie admin}: member must be 403 everywhere, admin must never be 401/403 (excluding `routes.py::ADMIN_PROBE_SKIP`), and no member response may contain the canary |
| D1 | cookie-authenticated member cannot export credentials — 403 with an authorization reason, canary absent |
| D2 | member cannot read the password from `GET /api/connections` or the detail route |
| D3 | cross-site attacker gets the canary from none of: form POST export, blind `text/plain` POST export, cross-origin `GET /api/connections` |
| D4 | positive control — the authorized admin **can** export the canary over the cookie path |
| E | unauthenticated browser -> 401 on both a safe and an unsafe method |
| E2 | cross-site attacker with **no** cookie -> 401, not 403: the auth layer answers, not CSRF |
| F | `GET` is never CSRF-blocked (cross-site GET reaches the handler and is 200) but is still authorization-checked (member -> 403 on `GET /api/settings` with an authz reason, 200 on `GET /api/connections`) |
| G | `Sec-Fetch-Site: none` is only ever produced by a user-initiated **GET** navigation; every page-initiated mutation is classified `cross-site` or `same-origin` |

## Observation techniques, and why they are needed

* **The uvicorn access log is the authoritative server-side observer.** When Chromium
  discards a cross-origin response for CORS it suppresses Playwright's `response`
  event entirely, even though the server received and processed the request — exactly
  the blind-CSRF case. The driver passes the gateway log path to the spec, which
  parses access lines for `"<METHOD> <path>" <status>`.
* **Browser-set request headers come from CDP.** `Request.allHeaders()` is also empty
  for a CORS-discarded response. `Network.requestWillBeSentExtraInfo` carries the
  real header set — including the network-service-added `Sec-Fetch-*` and `Cookie` —
  regardless of the CORS outcome. (Form submissions are navigations, so
  `allHeaders()` works there and is used directly.)
* **`SameSite=None` on the injected cookie is deliberate.** Clerk ships `__session`
  as `SameSite=Lax`, which would stop a cross-site POST inside the browser and prove
  nothing about the server. The cross-site tests set `None` so the middleware is the
  layer under test; A7 asserts the `Lax` behaviour separately.

## What this does NOT cover

* **No Clerk hosted sign-in.** The session token is minted through the Clerk Backend
  API and injected as a cookie. A genuine UI sign-in would additionally exercise
  Clerk's own cookie attributes (`Secure`, `SameSite=Lax`, `Domain`, `Path`,
  `HttpOnly`), the `__client_uat` / handshake and token-refresh flow, and the
  Next.js `middleware.ts` gate. Driving that UI needs `@clerk/testing` (absent) and
  trips Clerk's bot detection.
* **No web-app (Next.js) browser coverage.** Deliberately skipped: it needs a cloud
  build plus a real sign-in. Everything here is gateway-level. Still untested in a
  browser: the app's own `middleware.ts` route protection, its `fetch` wrappers'
  credential mode, and whether the app ever sends `Authorization: Bearer` from the
  browser (which would silently bypass the CSRF middleware).
* **No `Referer`-only path.** `csrf.py` step 6 only runs when `Origin` is absent.
  Modern Chromium always sends `Origin` on mutations, so that branch is unreachable
  from a current browser and is not exercised here.
* **Chromium only.** Firefox/WebKit `Sec-Fetch-*` behaviour is assumed equivalent,
  not verified.
* **No subdomain / same-site attacker.** Step 4 accepts `same-site`, so in production
  any origin sharing the registrable domain (any `*.signalpilot.ai`, any port, any
  scheme) passes CSRF. That is a design property worth reviewing, not a test gap this
  suite can close with two loopback hostnames.

## Secrets

No secret value is printed, logged, or written to a file. Session tokens and the
canary password reach the Playwright process through environment variables only, and
the canary is only ever asserted for **absence**. The gateway subprocess environment
is built from an explicit OS-plumbing allowlist (inherited from
`tests/e2e_cloud/conftest.py::_child_env`), so no developer credential from the shell
or the repo `.env` can leak into the gateway under test; `CLERK_SECRET_KEY` is read by
the driver only and never passed to the gateway.
