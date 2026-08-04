/**
 * REAL-BROWSER coverage of the cloud-mode cookie (`__session`) auth + CSRF path.
 *
 * Every other cloud-mode E2E test authenticates with `Authorization: Bearer`, which
 * `CookieAuthCsrfMiddleware` explicitly exempts (csrf.py step 3).  This suite drives
 * the path a real browser actually uses: a genuine Clerk-signed session token in the
 * `__session` cookie, with `Origin` / `Sec-Fetch-Site` set by Chromium itself.
 *
 * The suite does NOT boot anything.  It is driven by
 * `signalpilot/gateway/tests/e2e_cloud/browser_driver.py`, which boots a cloud-mode
 * gateway, provisions real Clerk identities, seeds a canary credential, and passes
 * everything in through environment variables.  Run standalone and it skips.
 *
 * Origin topology (load-bearing):
 *   gateway   http://localhost:<p>    <- also SP_ALLOWED_ORIGINS
 *   attacker  http://127.0.0.1:<q>    <- a DIFFERENT site, so Chromium emits
 *                                        Sec-Fetch-Site: cross-site
 * Two ports on the same host would be same-SITE and would legitimately pass step 4.
 *
 * No secret value is written to a file or asserted on by value; the canary password
 * is only ever tested for *absence*.
 */

import { test, expect, type BrowserContext, type Page, type Browser } from "@playwright/test";
import { createServer, type Server } from "http";
import type { AddressInfo } from "net";
import { readFileSync } from "fs";

const GW = process.env.SP_BROWSER_GATEWAY_URL ?? "";
const ATTACKER = process.env.SP_BROWSER_ATTACKER_ORIGIN ?? "";
const ATTACKER_PORT = Number(process.env.SP_BROWSER_ATTACKER_PORT ?? "0");
const ADMIN_SESSION = process.env.SP_BROWSER_ADMIN_SESSION ?? "";
const MEMBER_SESSION = process.env.SP_BROWSER_MEMBER_SESSION ?? "";
const CANARY = process.env.SP_BROWSER_CANARY ?? "";
const CONN_NAME = process.env.SP_BROWSER_CONN_NAME ?? "";
const GW_LOG = process.env.SP_BROWSER_GATEWAY_LOG ?? "";

interface AdminRoute {
  method: string;
  path: string;
  url: string;
  guards: string[];
  admin_probe: boolean;
}
const ADMIN_ROUTES: AdminRoute[] = JSON.parse(process.env.SP_BROWSER_ADMIN_ROUTES ?? "[]");

const CONFIGURED = Boolean(GW && ATTACKER && ADMIN_SESSION && MEMBER_SESSION && CANARY);

// File-level conditional skip: the callback form is the one Playwright supports
// outside a test body.  Never a failure, so a CI runner without docker/Clerk is fine.
test.skip(
  () => !CONFIGURED,
  "cloud-mode cookie/CSRF suite is driven by tests/e2e_cloud/browser_driver.py " +
    "(needs docker, a throwaway Postgres DB and Clerk test credentials)",
);

// Detail strings the authorization layer emits.  Seeing one on a member response is
// the expected denial; seeing one on an admin response is a lockout regression.
const AUTHZ_DENIALS = [
  "Organization admin role required",
  "Insufficient scope",
  "Unknown authentication method",
  "Admin access required",
];
// Reasons a route may answer 403 for something other than authorization.
const NON_AUTHZ_403 = ["not available on the free plan", "Upgrade to", "plan limit"];

const CSRF_BODY = '{"detail":"Forbidden."}';
const EXPORT_URL = () => `${GW}/api/connections/export`;
// A mutating POST that takes NO request body — only query parameters.  This is the
// shape a cross-site HTML form CAN actually reach (no CORS preflight, no JSON
// content-type requirement), so the CSRF middleware is the only thing standing in
// front of it.  See README "what is genuinely reachable from a browser".
const CACHE_INVALIDATE_URL = () => `${GW}/api/cache/invalidate?connection_name=${CONN_NAME}`;

// ── attacker origin: a real HTTP server on a different site ───────────────────

let attackerServer: Server;

const ATTACK_PAGE = `<!doctype html><html><head><meta charset="utf-8">
<title>attacker</title></head><body><h1>attacker origin</h1></body></html>`;

test.beforeAll(async () => {
  if (!CONFIGURED) return;
  attackerServer = createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(ATTACK_PAGE);
  });
  await new Promise<void>((resolve, reject) => {
    attackerServer.once("error", reject);
    attackerServer.listen(ATTACKER_PORT, "127.0.0.1", () => resolve());
  });
  const addr = attackerServer.address() as AddressInfo;
  expect(addr.port, "attacker server must own the port the driver advertised").toBe(
    ATTACKER_PORT,
  );
});

test.afterAll(async () => {
  if (attackerServer) await new Promise<void>((r) => attackerServer.close(() => r()));
});

// ── cookie plumbing ──────────────────────────────────────────────────────────

type SameSite = "Lax" | "None" | "Strict";

/**
 * Inject a genuine Clerk session token as the `__session` cookie.
 *
 * `SameSite=None` is the deliberate default for the cross-site tests: Clerk itself
 * ships `__session` as `SameSite=Lax`, and Lax alone would stop a cross-site POST
 * before the request ever left the browser — which would prove nothing about the
 * server-side middleware.  Setting None removes that outer layer so the CSRF
 * middleware is the thing under test.  `secure` is required by Chromium alongside
 * SameSite=None, and Chromium permits Secure cookies on http://localhost /
 * http://127.0.0.1 because those are "potentially trustworthy" origins.
 * A separate test asserts the Lax behaviour as defence in depth.
 */
async function setSessionCookie(
  ctx: BrowserContext,
  token: string,
  sameSite: SameSite = "None",
): Promise<void> {
  const u = new URL(GW);
  await ctx.addCookies([
    {
      name: "__session",
      value: token,
      domain: u.hostname,
      path: "/",
      httpOnly: true,
      secure: sameSite === "None",
      sameSite,
    },
  ]);
}

// ── server-side observation: the uvicorn access log ──────────────────────────
// Chromium suppresses Playwright's `response` event for a CORS-blocked
// cross-origin response, so the access log is the only place the server's real
// answer to a blind cross-site request can be read.

function accessLogLines(): string[] {
  try {
    return readFileSync(GW_LOG, "utf8").split(/\r?\n/);
  } catch {
    return [];
  }
}

function accessLogLength(): number {
  return accessLogLines().length;
}

const ESC = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function matchesIn(since: number, method: string, path: string): RegExpMatchArray[] {
  const re = new RegExp(`"(${ESC(method)}) ${ESC(path)}(?:\\?[^"]*)? HTTP/1\\.[01]" (\\d{3})`);
  return accessLogLines()
    .slice(since)
    .map((l) => l.match(re))
    .filter((m): m is RegExpMatchArray => Boolean(m));
}

/** Statuses the server logged for `method path` since `since`, waiting briefly. */
async function accessLogStatuses(since: number, method: string, path: string): Promise<number[]> {
  for (let i = 0; i < 20; i++) {
    const found = matchesIn(since, method, path);
    if (found.length) return found.map((m) => Number(m[2]));
    await new Promise((r) => setTimeout(r, 250));
  }
  return [];
}

/** Every method the server logged for `path` since `since`. */
function accessLogMethods(since: number, path: string): string[] {
  const re = new RegExp(`"([A-Z]+) ${ESC(path)}(?:\\?[^"]*)? HTTP/1\\.[01]" (\\d{3})`);
  return accessLogLines()
    .slice(since)
    .map((l) => l.match(re))
    .filter((m): m is RegExpMatchArray => Boolean(m))
    .map((m) => m[1]);
}

/**
 * Record the FINAL request headers Chromium put on the wire, via CDP.
 *
 * `Request.allHeaders()` returns nothing for a fetch whose response Chromium
 * discarded for CORS — which is exactly the blind-CSRF case.  CDP's
 * `Network.requestWillBeSentExtraInfo` carries the real header set (including the
 * network-service-added `Sec-Fetch-*` and `Cookie`) regardless of the CORS outcome.
 */
async function headerRecorder(page: Page, urlPrefix: string) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  const meta = new Map<string, { url: string; method: string }>();
  const finalHeaders = new Map<string, Record<string, string>>();

  cdp.on("Network.requestWillBeSent", (e: { requestId: string; request?: { url?: string; method?: string } }) => {
    const url = e.request?.url ?? "";
    if (url.startsWith(urlPrefix)) meta.set(e.requestId, { url, method: e.request?.method ?? "" });
  });
  // ExtraInfo may arrive before or after requestWillBeSent; both are keyed by id
  // and only correlated at read time.
  cdp.on("Network.requestWillBeSentExtraInfo", (e: { requestId: string; headers?: Record<string, string> }) => {
    const lower: Record<string, string> = {};
    for (const [k, v] of Object.entries(e.headers ?? {})) lower[k.toLowerCase()] = String(v);
    finalHeaders.set(e.requestId, lower);
  });

  return {
    /** Final headers of the first recorded request with this method. */
    forMethod(method: string): Record<string, string> {
      for (const [id, m] of meta) {
        if (m.method === method && finalHeaders.has(id)) return finalHeaders.get(id)!;
      }
      return {};
    },
    methods(): string[] {
      return [...meta.values()].map((m) => m.method);
    },
    async detach(): Promise<void> {
      await cdp.detach().catch(() => undefined);
    },
  };
}

/** A page whose document origin is the gateway (real HTML: FastAPI's /docs). */
async function gatewayPage(ctx: BrowserContext): Promise<Page> {
  const page = await ctx.newPage();
  const resp = await page.goto(`${GW}/docs`, { waitUntil: "domcontentloaded" });
  expect(resp?.status(), "gateway /docs must serve a same-origin HTML document").toBeLessThan(400);
  await page.waitForFunction(() => Boolean(document.body));
  return page;
}

/** A page whose document origin is the attacker's. */
async function attackerPage(ctx: BrowserContext): Promise<Page> {
  const page = await ctx.newPage();
  const resp = await page.goto(`${ATTACKER}/`, { waitUntil: "domcontentloaded" });
  expect(resp?.status()).toBe(200);
  return page;
}

interface FetchResult {
  /** What the attacker's JS could observe. */
  js: { ok: boolean; status?: number; text?: string; error?: string };
  /** What the SERVER actually answered, read from the uvicorn access log. */
  serverStatuses: number[];
  /** The FINAL headers Chromium put on the wire, captured over CDP. */
  requestHeaders: Record<string, string>;
  /** Every method the server logged for this path during the window. */
  methodsSeen: string[];
}

/**
 * Issue a fetch from `page` to `targetUrl` and report BOTH what the page could see
 * and what the server actually answered.
 *
 * Neither half can use the ordinary Playwright event surface.  When Chromium blocks
 * a cross-origin response for CORS it suppresses the `response` event and refuses to
 * resolve `Request.allHeaders()` with the real header set — yet the server received
 * and processed the request.  That is precisely the blind-CSRF case, so:
 *   - the server's answer is read from the uvicorn access log, and
 *   - the browser-set headers are read from CDP requestWillBeSentExtraInfo.
 */
async function observedFetch(
  page: Page,
  targetUrl: string,
  init: { method: string; contentType?: string; body?: string },
): Promise<FetchResult> {
  const rec = await headerRecorder(page, targetUrl.split("?")[0]);
  const mark = accessLogLength();

  const js = await page.evaluate(
    async ({ targetUrl, init }) => {
      const headers: Record<string, string> = {};
      if (init.contentType) headers["Content-Type"] = init.contentType;
      try {
        const r = await fetch(targetUrl, {
          method: init.method,
          credentials: "include",
          headers,
          body: init.body,
        });
        return { ok: true, status: r.status, text: (await r.text()).slice(0, 2000) };
      } catch (e) {
        return { ok: false, error: String(e).slice(0, 300) };
      }
    },
    { targetUrl, init },
  );

  await page.waitForTimeout(750);
  const requestHeaders = rec.forMethod(init.method);
  await rec.detach();

  const path = new URL(targetUrl).pathname;
  const serverStatuses = await accessLogStatuses(mark, init.method, path);
  const methodsSeen = accessLogMethods(mark, path);

  return { js, serverStatuses, requestHeaders, methodsSeen };
}


interface FormResult {
  status: number;
  body: string;
  requestHeaders: Record<string, string>;
}

/**
 * Auto-submit an HTML form from `page` at `targetUrl`.  A top-level form submission
 * is the classic CSRF vector: it is not subject to CORS at all, needs no preflight,
 * and the browser sets Origin / Sec-Fetch-Site itself.  Because it is a navigation
 * we can read the gateway's real status and body.
 */
async function formPost(
  page: Page,
  targetUrl: string,
  fields: Record<string, string>,
  enctype = "application/x-www-form-urlencoded",
): Promise<FormResult> {
  const waiter = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().startsWith(targetUrl.split("?")[0]),
    { timeout: 30_000 },
  );
  await page.evaluate(
    ({ targetUrl, fields, enctype }) => {
      const f = document.createElement("form");
      f.method = "POST";
      f.action = targetUrl;
      f.enctype = enctype;
      for (const [k, v] of Object.entries(fields)) {
        const i = document.createElement("input");
        i.type = "hidden";
        i.name = k;
        i.value = v;
        f.appendChild(i);
      }
      document.body.appendChild(f);
      // Submit out of band: submitting inline destroys this execution context
      // mid-evaluate and the evaluate call would reject.
      setTimeout(() => f.submit(), 0);
    },
    { targetUrl, fields, enctype },
  );
  const resp = await waiter;
  return {
    status: resp.status(),
    body: await resp.text().catch(() => ""),
    requestHeaders: await resp.request().allHeaders().catch(() => ({})),
  };
}

/** Same-origin, cookie-authenticated fetch run from a gateway-origin document. */
async function apiFromGatewayPage(
  page: Page,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; text: string }> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 20_000);
      try {
        const r = await fetch(path, {
          method,
          credentials: "include",
          headers: body === undefined ? {} : { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: ctl.signal,
        });
        return { status: r.status, text: (await r.text()).slice(0, 4000) };
      } catch (e) {
        return { status: -1, text: String(e).slice(0, 300) };
      } finally {
        clearTimeout(timer);
      }
    },
    { method, path, body },
  );
}

async function ctxWith(browser: Browser, token: string | null, sameSite: SameSite = "None") {
  const ctx = await browser.newContext();
  if (token) await setSessionCookie(ctx, token, sameSite);
  return ctx;
}

// =============================================================================
// (0) the cookie path actually works — everything below is vacuous without this
// =============================================================================

test("cookie sanity: an injected __session cookie really authenticates", async ({ browser }) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await gatewayPage(ctx);
  const r = await apiFromGatewayPage(page, "GET", "/api/connections");
  expect(
    r.status,
    "the __session cookie did not authenticate — Chromium may have refused the " +
      "Secure/SameSite=None cookie, in which case every assertion below is vacuous",
  ).toBe(200);
  await ctx.close();
});

// =============================================================================
// (A) CSRF is real
// =============================================================================

test("A1 cross-site form POST with a valid __session cookie is 403 (browser-set headers)", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await attackerPage(ctx);
  const r = await formPost(page, CACHE_INVALIDATE_URL(), { csrf: "1" });

  expect(r.requestHeaders["sec-fetch-site"], "Chromium must have classified this cross-site").toBe(
    "cross-site",
  );
  expect(r.requestHeaders["origin"]).toBe(ATTACKER);
  expect(r.requestHeaders["authorization"]).toBeUndefined();
  expect(r.requestHeaders["cookie"], "the cookie must actually have been sent").toContain(
    "__session=",
  );
  expect(r.status, `expected a CSRF 403, got ${r.status}: ${r.body.slice(0, 300)}`).toBe(403);
  expect(r.body).toContain("Forbidden");
  expect(r.body).not.toContain("invalidated");
  await ctx.close();
});

test("A2 the SAME form POST from the gateway origin succeeds — so A1's 403 is CSRF, not validation or authz", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await gatewayPage(ctx);
  const r = await formPost(page, CACHE_INVALIDATE_URL(), { csrf: "1" });

  expect(r.requestHeaders["sec-fetch-site"]).toBe("same-origin");
  expect(r.status, `same-origin cookie mutation was blocked: ${r.body.slice(0, 300)}`).toBe(200);
  expect(r.body, "the handler must actually have run").toContain("invalidated");
  await ctx.close();
});

test("A3 cross-site form POST to the credential export route is 403 and returns no credential", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await attackerPage(ctx);
  const r = await formPost(page, EXPORT_URL(), {
    include_credentials: "true",
    confirm: "true",
  });

  expect(r.requestHeaders["sec-fetch-site"]).toBe("cross-site");
  expect(r.status, `credential export was not CSRF-blocked: ${r.body.slice(0, 300)}`).toBe(403);
  expect(r.body).toBe(CSRF_BODY);
  expect(r.body, "CREDENTIAL LEAK via cross-site form POST").not.toContain(CANARY);
  expect(r.body).not.toContain(CONN_NAME);
  await ctx.close();
});

test("A4 CSRF fires BEFORE body parsing: same form shape is 403 cross-site but 422 same-origin", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);

  const attacker = await attackerPage(ctx);
  const cross = await formPost(attacker, EXPORT_URL(), {
    include_credentials: "true",
    confirm: "true",
  });

  const same = await gatewayPage(ctx);
  const local = await formPost(same, EXPORT_URL(), {
    include_credentials: "true",
    confirm: "true",
  });

  expect(cross.status).toBe(403);
  // 422: the handler was reached and rejected a form-encoded body for a JSON model.
  // The point is that the two differ ONLY in origin, so 403 is attributable to CSRF.
  expect(
    local.status,
    `same-origin form POST should reach validation, got ${local.status}`,
  ).toBe(422);
  expect(local.body).not.toContain(CANARY);
  await ctx.close();
});

test("A5 blind cross-site fetch (text/plain, no preflight) is 403 server-side and unreadable by the attacker", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await attackerPage(ctx);
  const r = await observedFetch(page, EXPORT_URL(), {
    method: "POST",
    contentType: "text/plain",
    body: JSON.stringify({ include_credentials: true, confirm: true }),
  });

  expect(
    r.requestHeaders["sec-fetch-site"],
    "Chromium must have classified this cross-site",
  ).toBe("cross-site");
  expect(r.requestHeaders["origin"]).toBe(ATTACKER);
  expect(r.requestHeaders["authorization"]).toBeUndefined();
  expect(r.requestHeaders["cookie"], "the cookie must actually have been sent").toContain(
    "__session=",
  );
  expect(
    r.serverStatuses,
    `server answered ${r.serverStatuses} to a blind cross-site cookie mutation`,
  ).toEqual([403]);
  // CORS keeps the response opaque, so even a 200 would not have been readable —
  // but the mutation would have happened.  Both layers are asserted.
  expect(r.js.ok, "CORS should have made the response unreadable to the attacker").toBe(false);
  expect(r.js.error ?? "").toMatch(/fetch|Failed|CORS|TypeError/i);
  await ctx.close();
});

test("A6 cross-site PUT never reaches the handler (CORS preflight) and the resource is unchanged", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const before = await apiFromGatewayPage(await gatewayPage(ctx), "GET", "/api/settings");
  expect(before.status).toBe(200);
  const beforeLimit = JSON.parse(before.text).default_row_limit;

  const page = await attackerPage(ctx);
  const r = await observedFetch(page, `${GW}/api/settings`, {
    method: "PUT",
    contentType: "application/json",
    body: JSON.stringify({ default_row_limit: 4242 }),
  });

  expect(r.js.ok, "the attacker's PUT must not have succeeded").toBe(false);
  expect(
    r.serverStatuses,
    "PUT is not a CORS-safelisted method, so the browser must never have sent it",
  ).toEqual([]);
  expect(
    r.methodsSeen,
    `the server logged ${r.methodsSeen} for /api/settings — only the preflight OPTIONS ` +
      "should ever have arrived",
  ).not.toContain("PUT");

  const after = await apiFromGatewayPage(await gatewayPage(ctx), "GET", "/api/settings");
  expect(JSON.parse(after.text).default_row_limit, "cross-site PUT mutated state").toBe(
    beforeLimit,
  );
  await ctx.close();
});

test("A7 defence in depth: a SameSite=Lax __session cookie is not even sent cross-site", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION, "Lax");
  const page = await attackerPage(ctx);
  const r = await formPost(page, CACHE_INVALIDATE_URL(), { csrf: "1" });

  expect(r.requestHeaders["cookie"] ?? "").not.toContain("__session=");
  // No cookie -> the auth middleware answers, not the CSRF middleware.
  expect([401, 403]).toContain(r.status);
  expect(r.body).not.toContain("invalidated");
  await ctx.close();
});

// =============================================================================
// (B) same-origin cookie mutations still work
// =============================================================================

test("B1 same-origin cookie PUT /api/settings by an admin is allowed and takes effect", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await gatewayPage(ctx);

  const before = await apiFromGatewayPage(page, "GET", "/api/settings");
  expect(before.status).toBe(200);
  const original = JSON.parse(before.text);
  const target = (original.default_row_limit ?? 10000) === 7777 ? 8888 : 7777;

  const put = await apiFromGatewayPage(page, "PUT", "/api/settings", {
    ...original,
    default_row_limit: target,
  });
  expect([401, 403], `same-origin admin cookie mutation denied: ${put.text.slice(0, 300)}`).not.toContain(
    put.status,
  );
  expect(put.status).toBe(200);

  const after = await apiFromGatewayPage(page, "GET", "/api/settings");
  expect(JSON.parse(after.text).default_row_limit).toBe(target);

  // restore
  await apiFromGatewayPage(page, "PUT", "/api/settings", original);
  await ctx.close();
});

test("B2 same-origin cookie POST by an admin is not blocked by CSRF (placeholder body may 4xx, but never 401/403)", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await gatewayPage(ctx);
  const r = await apiFromGatewayPage(page, "POST", "/api/connections/parse-url", {
    url: ["postgresql", "://u:p@10.255.255.1:5432/db"].join(""),
  });
  expect([401, 403]).not.toContain(r.status);
  await ctx.close();
});

// =============================================================================
// (C) authorization holds on the COOKIE path, not just Bearer
// =============================================================================

test("C the full admin-route matrix over cookie auth: member 403, admin not 403", async ({
  browser,
}) => {
  test.setTimeout(15 * 60_000);
  expect(ADMIN_ROUTES.length, "route discovery produced nothing").toBeGreaterThan(10);

  const run = async (token: string) => {
    const ctx = await ctxWith(browser, token);
    const page = await gatewayPage(ctx);
    const out: Record<string, { status: number; text: string }> = {};
    for (const route of ADMIN_ROUTES) {
      const body = ["POST", "PUT", "PATCH"].includes(route.method) ? {} : undefined;
      out[`${route.method} ${route.path}`] = await apiFromGatewayPage(
        page,
        route.method,
        route.url,
        body,
      );
    }
    await ctx.close();
    return out;
  };

  const memberResults = await run(MEMBER_SESSION);
  const adminResults = await run(ADMIN_SESSION);

  const bypasses: string[] = [];
  const lockouts: string[] = [];
  const leaks: string[] = [];

  for (const route of ADMIN_ROUTES) {
    const id = `${route.method} ${route.path}`;
    const m = memberResults[id];
    if (m.status !== 403) {
      bypasses.push(`${id} -> member got ${m.status} (guards: ${route.guards.join(",")})`);
    }
    if (CANARY && m.text.includes(CANARY)) leaks.push(id);

    if (route.admin_probe) {
      const a = adminResults[id];
      if (a.status === 403 && !NON_AUTHZ_403.some((s) => a.text.includes(s))) {
        lockouts.push(`${id} -> admin got 403: ${a.text.slice(0, 160)}`);
      }
      if (a.status === 401) lockouts.push(`${id} -> admin got 401`);
    }
  }

  expect(
    leaks,
    `CREDENTIAL LEAK to a cookie-authenticated member on: ${leaks.join(", ")}`,
  ).toEqual([]);
  expect(
    bypasses,
    `AUTHORIZATION BYPASS on the cookie path (${bypasses.length}/${ADMIN_ROUTES.length}):\n` +
      bypasses.join("\n"),
  ).toEqual([]);
  expect(
    lockouts,
    `ADMIN LOCKOUT on the cookie path (${lockouts.length}):\n` + lockouts.join("\n"),
  ).toEqual([]);
});

// =============================================================================
// (D) credential exfiltration via the browser
// =============================================================================

test("D1 a cookie-authenticated member cannot export credentials", async ({ browser }) => {
  const ctx = await ctxWith(browser, MEMBER_SESSION);
  const page = await gatewayPage(ctx);
  const r = await apiFromGatewayPage(page, "POST", "/api/connections/export", {
    include_credentials: true,
    confirm: true,
  });
  expect(r.status, `CREDENTIAL EXFILTRATION BYPASS (cookie member): ${r.text.slice(0, 300)}`).toBe(
    403,
  );
  expect(r.text, "CREDENTIAL LEAK to a cookie-authenticated member").not.toContain(CANARY);
  expect(r.text).not.toContain(CONN_NAME);
  expect(AUTHZ_DENIALS.some((d) => r.text.includes(d))).toBe(true);
  await ctx.close();
});

test("D2 a cookie-authenticated member cannot read the credential from the CRUD routes", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, MEMBER_SESSION);
  const page = await gatewayPage(ctx);
  const list = await apiFromGatewayPage(page, "GET", "/api/connections");
  expect(list.status).toBe(200);
  expect(list.text, "CREDENTIAL LEAK from GET /api/connections").not.toContain(CANARY);
  const detail = await apiFromGatewayPage(page, "GET", `/api/connections/${CONN_NAME}`);
  expect(detail.text, "CREDENTIAL LEAK from the connection detail route").not.toContain(CANARY);
  await ctx.close();
});

test("D3 the canary is not reachable by a cross-site attacker on any method the browser will send", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await attackerPage(ctx);
  const seen: string[] = [];

  const form = await formPost(page, EXPORT_URL(), {
    include_credentials: "true",
    confirm: "true",
  });
  seen.push(form.body);

  const attacker2 = await attackerPage(ctx);
  const blind = await observedFetch(attacker2, EXPORT_URL(), {
    method: "POST",
    contentType: "text/plain",
    body: JSON.stringify({ include_credentials: true, confirm: true }),
  });
  seen.push(blind.js.text ?? "", blind.js.error ?? "");
  expect(blind.serverStatuses, "blind cross-site export must be CSRF-blocked").toEqual([403]);

  const attacker3 = await attackerPage(ctx);
  const getAttempt = await observedFetch(attacker3, `${GW}/api/connections`, { method: "GET" });
  seen.push(getAttempt.js.text ?? "");

  for (const body of seen) {
    expect(body, "CREDENTIAL LEAK to a cross-site attacker").not.toContain(CANARY);
  }
  // The GET is a safe method so CSRF lets it through; CORS is what keeps the
  // response body away from the attacker's JS.
  expect(getAttempt.js.ok, "cross-origin GET body must not be readable by the attacker").toBe(
    false,
  );
  await ctx.close();
});

test("D4 the authorized admin CAN export the canary — otherwise D1-D3 prove nothing", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await gatewayPage(ctx);
  const r = await apiFromGatewayPage(page, "POST", "/api/connections/export", {
    include_credentials: true,
    confirm: true,
  });
  expect(r.status).toBe(200);
  expect(
    r.text.includes(CANARY),
    "admin export no longer returns credential material — the negative " +
      "exfiltration assertions above are vacuous and must be redesigned",
  ).toBe(true);
  await ctx.close();
});

// =============================================================================
// (E) unauthenticated browser
// =============================================================================

test("E an unauthenticated browser gets 401 on both safe and unsafe methods", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, null);
  const page = await gatewayPage(ctx);

  const get = await apiFromGatewayPage(page, "GET", "/api/connections");
  expect(get.status).toBe(401);

  const post = await apiFromGatewayPage(page, "POST", "/api/connections/export", {
    include_credentials: true,
    confirm: true,
  });
  expect(post.status).toBe(401);
  expect(post.text).not.toContain(CANARY);
  await ctx.close();
});

test("E2 a cross-site attacker with NO cookie gets 401, not 403 — CSRF is not the layer that answers", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, null);
  const page = await attackerPage(ctx);
  const r = await formPost(page, CACHE_INVALIDATE_URL(), { csrf: "1" });
  expect(r.requestHeaders["cookie"] ?? "").not.toContain("__session=");
  expect(r.status).toBe(401);
  await ctx.close();
});

// =============================================================================
// (F) safe methods: not CSRF-blocked, still authorization-checked
// =============================================================================

test("F GET is never CSRF-blocked but is still subject to authorization", async ({ browser }) => {
  const memberCtx = await ctxWith(browser, MEMBER_SESSION);
  const memberPage = await gatewayPage(memberCtx);

  // Admin-gated GET: denied by authorization, with an authz reason (not the CSRF body).
  const gated = await apiFromGatewayPage(memberPage, "GET", "/api/settings");
  expect(gated.status).toBe(403);
  expect(gated.text).not.toBe(CSRF_BODY);
  expect(AUTHZ_DENIALS.some((d) => gated.text.includes(d))).toBe(true);

  // Ordinary member GET: allowed.
  const ok = await apiFromGatewayPage(memberPage, "GET", "/api/connections");
  expect(ok.status).toBe(200);
  await memberCtx.close();

  // A cross-site GET is not blocked by CSRF either: the server answers 200 even
  // though CORS hides the body from the attacker (asserted in D3).
  const adminCtx = await ctxWith(browser, ADMIN_SESSION);
  const attacker = await attackerPage(adminCtx);
  const cross = await observedFetch(attacker, `${GW}/api/connections`, { method: "GET" });
  expect(cross.requestHeaders["sec-fetch-site"]).toBe("cross-site");
  expect(
    cross.serverStatuses,
    "safe methods must bypass the CSRF middleware, whatever the origin",
  ).toEqual([200]);
  // CORS still hides the body from the attacker's JS (D3 asserts the canary too).
  expect(cross.js.ok).toBe(false);
  await adminCtx.close();
});

// =============================================================================
// (G) is `Sec-Fetch-Site: none` exploitable from a real browser?
// =============================================================================

test("G Sec-Fetch-Site: none is only produced by user-initiated navigation, which cannot carry a mutation", async ({
  browser,
}) => {
  const ctx = await ctxWith(browser, ADMIN_SESSION);
  const page = await ctx.newPage();

  // An address-bar / bookmark style navigation is the ONLY way to get "none".
  const captured: { method: string; site: string | undefined }[] = [];
  page.on("request", async (req) => {
    if (!req.url().startsWith(GW)) return;
    if (req.resourceType() !== "document") return;
    const h = await req.allHeaders().catch(() => ({}) as Record<string, string>);
    captured.push({ method: req.method(), site: h["sec-fetch-site"] });
  });
  await page.goto(`${GW}/docs`, { waitUntil: "domcontentloaded" });
  const nav = captured.find((c) => c.site === "none");
  expect(nav, "expected a Sec-Fetch-Site: none navigation").toBeTruthy();
  expect(
    nav!.method,
    "a Sec-Fetch-Site: none request can only ever be a GET navigation — there is no " +
      "browser API that produces a POST with Sec-Fetch-Site: none",
  ).toBe("GET");

  // And a page-initiated mutation is never classified "none", whatever the origin.
  const attacker = await attackerPage(ctx);
  const cross = await formPost(attacker, CACHE_INVALIDATE_URL(), { g: "1" });
  expect(cross.requestHeaders["sec-fetch-site"]).toBe("cross-site");

  const local = await gatewayPage(ctx);
  const same = await formPost(local, CACHE_INVALIDATE_URL(), { g: "1" });
  expect(same.requestHeaders["sec-fetch-site"]).toBe("same-origin");

  await ctx.close();
});
