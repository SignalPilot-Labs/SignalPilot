"""Boot a cloud-mode gateway + real Clerk identities, then hand them to Playwright.

Why this exists
---------------
Every existing cloud-mode E2E test authenticates with ``Authorization: Bearer``.
``CookieAuthCsrfMiddleware`` explicitly *exempts* Bearer callers, so the code path a
real browser actually uses — the ``__session`` cookie plus browser-set
``Origin`` / ``Sec-Fetch-Site`` — was entirely untested.  This driver closes that gap:

1. provisions a throwaway Clerk org with a real admin and a real ``org:member``
   (``tests/e2e_cloud/clerk_backend.py``),
2. boots a real uvicorn gateway in ``SP_DEPLOYMENT_MODE=cloud`` against a throwaway
   Postgres database inside the existing dev container,
3. seeds a connection carrying a canary password (the exfiltration target),
4. discovers every admin-gated route from the live FastAPI dependency tree,
5. runs the Playwright suite in ``signalpilot/web/e2e/cloud-cookie-csrf/``, handing it
   everything through **environment variables only**,
6. tears down the connection, the gateway, and every Clerk resource it created.

Addressing note (load-bearing)
------------------------------
``gateway/main.py::_build_allowed_origins`` keeps an origin in cloud mode only if it
is ``https://`` or starts with ``http://localhost``.  A ``http://127.0.0.1:<port>``
entry is dropped.  So the gateway is *addressed* as ``http://localhost:<port>`` and
``SP_ALLOWED_ORIGINS`` is set to match, while the attacker page is served from
``http://127.0.0.1:<port>``.  ``localhost`` and ``127.0.0.1`` are different sites, so
Chromium computes ``Sec-Fetch-Site: cross-site`` for attacker -> gateway requests.
Using two *ports* on the same host would be same-**site** and would legitimately pass
the middleware's step 4.

Secrets
-------
No secret value is printed or written to a file.  Session tokens and the canary
password are passed to the Playwright child through its environment only.

Usage
-----
    cd signalpilot/gateway
    python -m tests.e2e_cloud.browser_driver             # boot + run the suite
    python -m tests.e2e_cloud.browser_driver --baseline  # same, tolerate failures

Exit code 0 = suite passed, 1 = suite failed, 2 = prerequisites unavailable (skip).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = GATEWAY_DIR.parent.parent
WEB_DIR = REPO_ROOT / "signalpilot" / "web"
SPEC_REL = "e2e/cloud-cookie-csrf/cookie-csrf.spec.ts"

PREFERRED_GATEWAY_PORT = int(os.environ.get("SP_BROWSER_GATEWAY_PORT", "3397"))
PREFERRED_ATTACKER_PORT = int(os.environ.get("SP_BROWSER_ATTACKER_PORT", "4501"))
BROWSER_DB_NAME = "sp_e2e_browser"
CONN_NAME = "e2e-browser-canary"

SKIP = 2


def _log(msg: str) -> None:
    print(f"[browser-driver] {msg}", flush=True)


def _port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _npx() -> str | None:
    return shutil.which("npx") or shutil.which("npx.cmd")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true",
                        help="report the suite result but always exit 0 (for stashed-fix runs)")
    args = parser.parse_args()

    import pytest  # only used for its Skipped exception type

    from . import conftest as cc
    from .clerk_backend import ClerkError, load_env_value, provision, sweep_stale
    from .routes import ADMIN_PROBE_SKIP, discover

    if _npx() is None:
        _log("npx not on PATH - cannot run Playwright")
        return SKIP
    if not (WEB_DIR / "node_modules" / "@playwright" / "test").exists():
        _log("@playwright/test not installed in signalpilot/web - skipping")
        return SKIP

    # ── prerequisites: docker + throwaway database ────────────────────────────
    try:
        cc._require_db_container()
        database_url = cc._fresh_database(BROWSER_DB_NAME)
    except pytest.skip.Exception as e:  # type: ignore[attr-defined]
        _log(f"database unavailable: {e}")
        return SKIP

    pk = load_env_value("CLERK_PUBLISHABLE_KEY", REPO_ROOT)
    sk = load_env_value("CLERK_SECRET_KEY", REPO_ROOT)
    if not pk or not sk:
        _log("CLERK_PUBLISHABLE_KEY / CLERK_SECRET_KEY absent from repo-root .env")
        return SKIP
    if not pk.startswith("pk_test_"):
        _log("refusing to run: CLERK_PUBLISHABLE_KEY is not a pk_test_ key")
        return SKIP

    # ── real Clerk identities ─────────────────────────────────────────────────
    try:
        for line in sweep_stale(sk):
            _log(f"clerk sweep: {line}")
        fixture = provision(sk)
    except (ClerkError, OSError) as e:
        _log(f"could not provision Clerk resources: {e}")
        return SKIP
    _log(f"clerk: org={fixture.org_id} admin={fixture.admin_user_id} member={fixture.member_user_id}")
    admin_rol = (fixture.admin_claims.get("o") or {}).get("rol")
    member_rol = (fixture.member_claims.get("o") or {}).get("rol")
    _log(f"clerk claim roles: admin o.rol={admin_rol!r} member o.rol={member_rol!r}")
    if member_rol == admin_rol:
        _log("FATAL: member and admin carry the same role claim - fixture unsafe")
        for line in fixture.cleanup():
            _log(f"clerk cleanup: {line}")
        return SKIP

    gateway_port = PREFERRED_GATEWAY_PORT if _port_is_free(PREFERRED_GATEWAY_PORT) else 0
    if gateway_port == 0:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            gateway_port = s.getsockname()[1]
    attacker_port = PREFERRED_ATTACKER_PORT if _port_is_free(PREFERRED_ATTACKER_PORT) else 0
    if attacker_port == 0:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            attacker_port = s.getsockname()[1]

    # Addressed via localhost (see module docstring) so the origin survives
    # _build_allowed_origins() and so the attacker on 127.0.0.1 is cross-SITE.
    gateway_url = f"http://localhost:{gateway_port}"
    attacker_url = f"http://127.0.0.1:{attacker_port}"

    cc.seed_plan_tier(BROWSER_DB_NAME, fixture.org_id)

    workdir = Path(os.environ.get("TEMP", "/tmp")) / f"sp-browser-e2e-{secrets.token_hex(4)}"
    workdir.mkdir(parents=True, exist_ok=True)
    env = cc._child_env(workdir, database_url, gateway_port, pk,
                        ca_file=None, expected_azp=None,
                        session_jwt_secret=secrets.token_urlsafe(32))
    env["SP_ALLOWED_ORIGINS"] = gateway_url
    env["SP_PUBLIC_GATEWAY_URL"] = gateway_url

    proc = log_fh = None
    rc = SKIP
    try:
        try:
            proc, log_fh, log_path = cc._boot(env, gateway_port, workdir, "browser-csrf")
        except pytest.skip.Exception as e:  # type: ignore[attr-defined]
            _log(f"gateway did not boot: {e}")
            return SKIP
        _log(f"gateway up at {gateway_url} (log: {log_path})")

        import httpx

        canary = "BrowserCsrfCanary" + secrets.token_hex(8)
        with httpx.Client(base_url=gateway_url, timeout=60.0) as http:
            hdr = {"Authorization": f"Bearer {fixture.admin_token}", "Origin": gateway_url}
            created = http.post("/api/connections", headers=hdr, json={
                "name": CONN_NAME,
                "db_type": "postgres",
                # Loopback is blocked unconditionally by the SSRF guard; an unrouted
                # RFC1918 address validates instead (SP_ALLOW_PRIVATE_CONNECTIONS=1).
                "host": "10.255.255.1", "port": 5432, "database": "e2e",
                "username": "e2e_user", "password": canary,
                "description": "browser csrf exfiltration canary",
            })
            if created.status_code not in (200, 201):
                _log(f"could not seed canary connection: {created.status_code} "
                     f"{created.text[:200]}")
                return SKIP
            # Confirm the canary really is exfiltratable by an authorized admin,
            # otherwise the negative assertions in the browser suite are vacuous.
            probe = http.post("/api/connections/export", headers=hdr,
                              json={"include_credentials": True, "confirm": True})
            if probe.status_code != 200 or canary not in probe.text:
                _log("admin Bearer export did not return the canary - the browser "
                     "exfiltration assertions would be vacuous")
                return SKIP
            _log("canary is confirmed exfiltratable by an authorized admin (Bearer)")

            baseline_settings = http.get("/api/settings", headers=hdr)
            baseline_row_limit = (baseline_settings.json() or {}).get("default_row_limit")

        admin_routes, _scoped = discover()
        route_payload = [
            {"method": r.method, "path": r.path, "url": r.url,
             "guards": list(r.guards),
             "admin_probe": (r.method, r.path) not in ADMIN_PROBE_SKIP}
            for r in admin_routes
        ]
        _log(f"discovered {len(route_payload)} admin-gated routes")

        child = dict(os.environ)
        child |= {
            "SP_BROWSER_GATEWAY_URL": gateway_url,
            "SP_BROWSER_ATTACKER_ORIGIN": attacker_url,
            "SP_BROWSER_ATTACKER_PORT": str(attacker_port),
            "SP_BROWSER_ADMIN_SESSION": fixture.admin_token,
            "SP_BROWSER_MEMBER_SESSION": fixture.member_token,
            "SP_BROWSER_ADMIN_ROUTES": json.dumps(route_payload),
            "SP_BROWSER_CANARY": canary,
            "SP_BROWSER_CONN_NAME": CONN_NAME,
            "SP_BROWSER_BASELINE_ROW_LIMIT": str(baseline_row_limit),
            # The uvicorn access log is the only authoritative view of what the
            # server actually answered to a CORS-blocked cross-site request:
            # Chromium suppresses the Playwright `response` event in that case.
            "SP_BROWSER_GATEWAY_LOG": str(log_path),
        }
        cmd = [_npx(), "playwright", "test", SPEC_REL, "--reporter=list"]
        _log(f"running: {' '.join(cmd)} (cwd={WEB_DIR})")
        result = subprocess.run(cmd, cwd=str(WEB_DIR), env=child)
        rc = result.returncode
        _log(f"playwright exit code {rc}")

        with httpx.Client(base_url=gateway_url, timeout=60.0) as http:
            hdr = {"Authorization": f"Bearer {fixture.admin_token}", "Origin": gateway_url}
            http.delete(f"/api/connections/{CONN_NAME}", headers=hdr)
        return 0 if args.baseline else rc
    finally:
        if proc is not None:
            cc._shutdown(proc, log_fh)
            _log("gateway stopped")
        for line in fixture.cleanup():
            _log(f"clerk cleanup: {line}")


if __name__ == "__main__":
    sys.exit(main())
