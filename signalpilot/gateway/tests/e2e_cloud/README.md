# Cloud-mode end-to-end authorization harness

Boots the gateway as a **real uvicorn subprocess** in `SP_DEPLOYMENT_MODE=cloud`,
against a **throwaway Postgres database**, and drives the full authorization matrix
over **real HTTP** with **real RS256 JWT verification**.

There is no `TestClient`, no dependency override, and no monkeypatching of
`jwt.decode` or of the JWKS key lookup.

## Running it

```bash
cd signalpilot/gateway

# everything
python -m pytest tests/e2e_cloud/ -q

# only the synthetic-JWKS suite (no network, no Clerk account needed)
python -m pytest tests/e2e_cloud/ -q --ignore=tests/e2e_cloud/test_real_clerk.py

# only the real-Clerk suite
python -m pytest tests/e2e_cloud/test_real_clerk.py -q

# by marker, from a full-suite run
python -m pytest -m e2e_cloud -q
```

Runtime is roughly 20-30 seconds for the whole suite.

### Prerequisites

| Requirement | If missing |
| --- | --- |
| `docker` CLI on PATH | whole suite `pytest.skip`s |
| container `signalpilot-db-1` running (127.0.0.1:5601) | whole suite skips |
| `uvicorn` importable | skips with the boot log tail |
| `CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY` in the repo-root `.env` | only `test_real_clerk.py` skips |
| outbound network to `api.clerk.com` | only `test_real_clerk.py` skips |

Every failure mode is a `pytest.skip`, never a failure, so a CI runner without
docker is unaffected. All tests carry `@pytest.mark.e2e_cloud` (registered in
`pyproject.toml`).

### What it touches

* Creates and drops the databases `sp_e2e_cloud` and `sp_e2e_cloud_real` inside the
  **existing** dev Postgres container. It never connects to or writes to the
  `signalpilot` database. Both are dropped and recreated at the start of every run,
  and left in place afterwards so a failure can be inspected.

  The two gateways deliberately do **not** share a database. `init_db()` issues ~40
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements at every boot, each taking an
  `ACCESS EXCLUSIVE` lock with no `lock_timeout`, while the health-ping loop holds a
  DB session open across slow warehouse I/O. Booting a second gateway against a
  database the first one is using deadlocks on a relation lock — the harness hit this
  for real. See the finding note in the task report.
* Binds two free localhost ports, preferring 3399 and 3398 and falling back to
  OS-assigned ephemeral ports if those are taken. Never touches the running dev
  stack on 3300/3200/2718.
* `test_real_clerk.py` creates exactly **two throwaway Clerk users, one throwaway
  organization, and two sessions**, then revokes the sessions and deletes the
  organization and users in fixture teardown. It never modifies pre-existing users,
  organizations, or memberships.

## How cloud mode is reached offline

`gateway/auth/user.py::_get_jwks_client` derives both the JWKS URL and the expected
issuer by base64-decoding the domain out of `CLERK_PUBLISHABLE_KEY`:

```
pk_test_<base64("domain$")>  ->  https://<domain>/.well-known/jwks.json
                                 issuer = https://<domain>
```

`tests/e2e_cloud/jwks.py` exploits this: it starts a local HTTPS server, encodes
`127.0.0.1:<port>` as the domain, and hands the gateway a synthetic `pk_test_` key.
TLS trust comes from a runtime-generated self-signed certificate (SAN
`IP:127.0.0.1`) passed to the child via `SSL_CERT_FILE`, which
`ssl.create_default_context()` — and therefore `urllib`, and therefore
`jwt.PyJWKClient` — honours.

**Fidelity:** the gateway performs a genuine HTTPS JWKS fetch, genuine RS256
signature verification, genuine issuer matching, genuine
`require=[exp, iat, sub]`, and the genuine `azp` check. The *only* difference from
production is which key pair signs the token.

## Test modules

| Module | Covers |
| --- | --- |
| `jwks.py` | local HTTPS JWKS server + Clerk-shaped token minting |
| `clerk_backend.py` | Clerk Backend API client that provisions and tears down throwaway users/orgs/sessions |
| `routes.py` | discovers admin-gated routes from the app's dependency tree; curated member-route list |
| `test_jwt_verification.py` | authentication: expired, forged signature, wrong issuer, wrong `azp`, `alg=none`, missing `sub`/`exp`/`iat`, no token, missing org claim |
| `test_admin_matrix.py` | the full matrix across every discovered admin route x six caller identities, plus the member-lockout regression check |
| `test_exploits.py` | the concrete pre-fix exploits, including a credential-material scan of every denial body |
| `test_api_key_roles.py` | API keys cannot outrank their own scopes |
| `test_notebook_session_scope.py` | a pod-callback JWT that *asks* for `admin` in its own `scopes` claim cannot get it |
| `test_credential_exfiltration.py` | seeds a real password, proves admin export returns it, proves nobody else can |
| `test_real_clerk.py` | the same matrix using **genuine Clerk-signed tokens** verified against the **real Clerk JWKS** |

## Route discovery is not hand-maintained

`routes.py::discover()` walks the live FastAPI dependency tree, identifying
`require_org_admin` by object identity and `RequireScope("admin")` by reading the
scope tuple out of the closure cell. A newly added admin route is therefore covered
automatically, and a route that silently *loses* its guard shows up as a matrix
failure rather than quietly disappearing from the test set.

Discovery runs in a subprocess with `SP_DEPLOYMENT_MODE=cloud`, because
`gateway/api/__init__.py` skips the `files`, `projects` and `sandboxes` routers in
cloud mode. Discovering in local mode would ask for routes that legitimately 404.

## Deliberate exclusions

Both are documented in `routes.py`:

* **`ADMIN_PROBE_SKIP`** — routes not driven with an admin token because a
  *successful* call reaches the network or spawns work (`POST /api/demo/connector`,
  `POST /api/github/bot/scan`, `POST /api/evals/runs`). The deny-side assertions
  still cover them.
* **`GET /api/security/status`** — layers a second, stricter check on top of
  `OrgAdmin`: `security.py::_require_admin` also requires the caller's user id to be
  in `SP_ADMIN_USER_IDS` (a platform-operator allowlist, default `{"local"}`). An org
  admin who is not a platform operator is *correctly* 403 there, so only the deny
  side is asserted.

## Distinguishing authorization 403s from policy 403s

Member routes may legitimately answer 403 for plan gating
(`"... is not available on the free plan"`). The harness pins the test orgs to the
`unlimited` tier by seeding the backend-owned `subscriptions` table, and
additionally asserts that no member response carries an authorization denial string
(`"Organization admin role required"`, `"Insufficient scope"`, …). A member lockout
regression is treated as seriously as a bypass.

## Secrets

No secret value is ever printed, logged, or written to a file.
`SP_ENCRYPTION_KEY` and `SP_SESSION_JWT_SECRET` are freshly generated Fernet keys
per run. The child process environment is built from an explicit OS-plumbing
allowlist rather than inherited, so no developer credential from the shell or the
repo `.env` can reach the gateway under test — except `CLERK_PUBLISHABLE_KEY` in
`test_real_clerk.py`, which is a public key by design. `CLERK_SECRET_KEY` is read by
the test process only, and is never passed to the gateway subprocess.
