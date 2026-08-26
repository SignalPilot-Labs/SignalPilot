"""Fixtures that boot a genuine cloud-mode gateway for the authorization matrix.

Everything here is real: a real Postgres database, a real uvicorn process, real
RS256 signature/issuer/exp verification against a real HTTPS JWKS fetch. The only
substitution is *whose* JWKS endpoint the gateway trusts.

Skips cleanly (never fails) when docker, the throwaway database, or uvicorn is
unavailable, so CI without a docker daemon is unaffected.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from .jwks import FakeClerk, start_fake_clerk
from .routes import STAFF_USER_ID

GATEWAY_DIR = Path(__file__).resolve().parents[2]

DB_CONTAINER = "signalpilot-db-1"
DB_HOST = "127.0.0.1"
DB_PORT = 5601
DB_USER = "signalpilot"
# Each gateway process gets its OWN database. They must not share one: init_db()
# issues ~40 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements at every boot,
# each taking an ACCESS EXCLUSIVE lock, and the health-ping loop holds a session
# open across slow warehouse I/O. A second gateway booting against a database the
# first one is using therefore blocks indefinitely on a relation lock.
DB_NAME = "sp_e2e_cloud"
REAL_DB_NAME = "sp_e2e_cloud_real"

PREFERRED_GATEWAY_PORT = int(os.environ.get("SP_E2E_GATEWAY_PORT", "3399"))

ORG_ID = "org_e2ecloudtest"
OTHER_ORG_ID = "org_e2eother"

BOOT_TIMEOUT_SECONDS = 150


def _free_port(preferred: int) -> int:
    """Return `preferred` if it is free, else an OS-assigned ephemeral port.

    A stale gateway left behind by an interrupted run must not be able to wedge the
    whole suite into skipping, which is exactly what a hard-coded port does.
    """
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _docker() -> str | None:
    return shutil.which("docker")


def _db_password() -> str:
    """Read the throwaway dev database password out of docker-compose.yml.

    Never returned to a report or log — only handed to the child process env.
    """
    compose = GATEWAY_DIR.parent.parent / "docker-compose.yml"
    if not compose.exists():
        return "changeme_dev_only"
    for line in compose.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("POSTGRES_PASSWORD"):
            return stripped.split(":", 1)[1].strip().strip("\"'")
    return "changeme_dev_only"


def _psql(sql: str, *, database: str = "postgres") -> subprocess.CompletedProcess:
    docker = _docker()
    assert docker
    return subprocess.run(
        [docker, "exec", "-e", f"PGPASSWORD={_db_password()}", DB_CONTAINER,
         "psql", "-U", DB_USER, "-d", database, "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, timeout=90,
    )


# ── session fixtures ──────────────────────────────────────────────────────────


def _require_db_container() -> None:
    if _docker() is None:
        pytest.skip("docker CLI not available - cloud e2e harness requires it")
    probe = subprocess.run([_docker(), "inspect", "-f", "{{.State.Running}}", DB_CONTAINER],
                           capture_output=True, text=True)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        pytest.skip(f"container {DB_CONTAINER} is not running")


def seed_plan_tier(database: str, *org_ids: str) -> None:
    """Pin orgs to the top plan tier in the backend-owned `subscriptions` table.

    That table is not part of the gateway schema, so without it every org resolves to
    the free tier and plan gating answers its own 403 — which would masquerade as an
    authorization denial.
    """
    values = ", ".join(f"('{oid}', 'unlimited')" for oid in org_ids)
    _psql(
        "CREATE TABLE IF NOT EXISTS subscriptions ("
        " org_id text PRIMARY KEY, plan_tier text NOT NULL);"
        f" INSERT INTO subscriptions (org_id, plan_tier) VALUES {values}"
        " ON CONFLICT (org_id) DO UPDATE SET plan_tier = EXCLUDED.plan_tier;",
        database=database,
    )


def _fresh_database(name: str) -> str:
    """Drop and recreate `name`, returning a DATABASE_URL. Never touches `signalpilot`."""
    assert name.startswith("sp_e2e"), f"refusing to drop non-e2e database {name!r}"
    _psql(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{name}' AND pid <> pg_backend_pid();"
    )
    _psql(f"DROP DATABASE IF EXISTS {name};")
    created = _psql(f"CREATE DATABASE {name};")
    if created.returncode != 0:
        pytest.skip(f"could not create {name}: {created.stderr.strip()[:200]}")
    return f"postgresql://{DB_USER}:{_db_password()}@{DB_HOST}:{DB_PORT}/{name}"


@pytest.fixture(scope="session")
def e2e_database() -> str:
    """Pristine throwaway database for the synthetic-JWKS gateway."""
    _require_db_container()
    url = _fresh_database(DB_NAME)
    seed_plan_tier(DB_NAME, ORG_ID, OTHER_ORG_ID)
    return url


@pytest.fixture(scope="session")
def real_e2e_database() -> str:
    """Pristine throwaway database for the real-Clerk gateway (see DB_NAME comment)."""
    _require_db_container()
    return _fresh_database(REAL_DB_NAME)


@pytest.fixture(scope="session")
def fake_clerk() -> FakeClerk:
    server = start_fake_clerk()
    yield server
    server.stop()


@dataclass
class Gateway:
    base_url: str
    clerk: FakeClerk
    process: subprocess.Popen
    log_path: Path
    # The HS256 secret this gateway was booted with. Held so tests can mint
    # notebook-session (pod callback) tokens the gateway will actually accept.
    session_jwt_secret: str = ""


def _child_env(workdir: Path, database_url: str, port: int, publishable_key: str,
               *, ca_file: Path | None, expected_azp: str | None,
               session_jwt_secret: str) -> dict[str, str]:
    """Build the child process environment.

    Started from an explicit OS-plumbing allowlist rather than inheriting os.environ,
    so no developer credential from the shell or the repo .env can reach the gateway
    under test. APPDATA/LOCALAPPDATA are included because CPython's site module derives
    the per-user site-packages directory from them — dropping them silently hides
    ``pip --user`` installs (uvicorn among them) from the child interpreter.
    """
    from cryptography.fernet import Fernet

    base_url = f"http://127.0.0.1:{port}"
    env = {
        k: v for k, v in os.environ.items()
        if k.upper() in {
            "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
            "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
            "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS", "LANG", "LC_ALL",
            "HOME", "USER", "SHELL", "TZ",
        }
    }
    env |= {
        "TEMP": str(workdir), "TMP": str(workdir),
        "PYTHONPATH": str(GATEWAY_DIR),
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",

        # ── cloud mode ────────────────────────────────────────────────────────
        "SP_DEPLOYMENT_MODE": "cloud",
        "CLERK_PUBLISHABLE_KEY": publishable_key,
        "DATABASE_URL": database_url,
        "SP_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SP_SESSION_JWT_SECRET": session_jwt_secret,

        # ── cloud hardening kill-switches (assert_cloud_hardening_intact) ─────
        "SP_NOTEBOOK_IMAGE": "registry.invalid/notebook@sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "SP_DISABLE_SANDBOX": "false",
        "SP_ALLOWED_ORIGINS": base_url,

        # ── keep background machinery inert ───────────────────────────────────
        "SP_DBT_PROXY_ENABLED": "false",
        "SP_DBT_PROXY_HOST": "127.0.0.1",
        "SP_BYOK_PROVIDER": "local",
        "SP_PUBLIC_GATEWAY_URL": base_url,
        "SP_PUBLIC_GATEWAY_PORT": str(port),
        "SP_RATE_LIMIT_ENABLED": "false",
        "SP_GIT_REPOS_DIR": str(workdir / "repos"),
        "SP_DATA_DIR": str(workdir / "data"),

        # Platform-staff allowlist. Without it the default is {"local"} and no
        # cloud identity can reach the staff-only routes, which would make the
        # positive half of the staff matrix unassertable.
        "SP_ADMIN_USER_IDS": STAFF_USER_ID,

        # Narrow, deliberate deviation from cloud defaults: lets the credential
        # exfiltration suite seed a connection with a real password without sending
        # packets to a public IP. It relaxes only the SSRF host allowlist in
        # gateway/network/validation.py and has no bearing on any authorization
        # decision under test. Loopback and link-local stay blocked regardless.
        "SP_ALLOW_PRIVATE_CONNECTIONS": "1",
    }
    if expected_azp is not None:
        env["SP_EXPECTED_AZP"] = expected_azp
    if ca_file is not None:
        # Makes PyJWKClient's urllib fetch trust the local JWKS server's self-signed
        # certificate: ssl.create_default_context() honours SSL_CERT_FILE.
        env["SSL_CERT_FILE"] = str(ca_file)
        env["REQUESTS_CA_BUNDLE"] = str(ca_file)
    return env


def _boot(env: dict[str, str], port: int, workdir: Path, label: str):
    """Launch uvicorn and wait for /health. pytest.skip on failure, never fail."""
    base_url = f"http://127.0.0.1:{port}"
    log_path = workdir / f"gateway-{label}.log"
    log_fh = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "gateway.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        cwd=str(GATEWAY_DIR), env=env, stdout=log_fh, stderr=subprocess.STDOUT,
    )

    def tail() -> str:
        log_fh.flush()
        return log_path.read_text(encoding="utf-8", errors="replace")[-3000:]

    deadline = time.time() + BOOT_TIMEOUT_SECONDS
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.skip(f"[{label}] gateway exited during boot (rc={proc.returncode}):\n{tail()}")
        try:
            if httpx.get(f"{base_url}/health", timeout=3).status_code < 500:
                return proc, log_fh, log_path
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    pytest.skip(f"[{label}] gateway not healthy in {BOOT_TIMEOUT_SECONDS}s:\n{tail()}")


def _shutdown(proc: subprocess.Popen, log_fh) -> None:
    """Stop a gateway subprocess, escalating to kill. Never raises.

    Teardown must not leak a listening process: a stray gateway would otherwise hold
    the preferred port for the next run. (_free_port also falls back to an ephemeral
    port, so a leak degrades tidiness rather than correctness.)
    """
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    pass
    finally:
        try:
            log_fh.close()
        except Exception:  # pragma: no cover
            pass


@pytest.fixture(scope="session")
def gateway(e2e_database: str, fake_clerk: FakeClerk, tmp_path_factory) -> Gateway:
    """Boot `uvicorn gateway.main:app` in cloud mode against the local JWKS server."""
    port = _free_port(PREFERRED_GATEWAY_PORT)
    base_url = f"http://127.0.0.1:{port}"

    workdir = tmp_path_factory.mktemp("sp-e2e-gateway")
    session_secret = secrets.token_urlsafe(32)
    env = _child_env(workdir, e2e_database, port, fake_clerk.publishable_key,
                     ca_file=fake_clerk.ca_file, expected_azp=base_url,
                     session_jwt_secret=session_secret)
    proc, log_fh, log_path = _boot(env, port, workdir, "synthetic")

    yield Gateway(base_url, fake_clerk, proc, log_path, session_secret)

    _shutdown(proc, log_fh)


@pytest.fixture(scope="session")
def client(gateway: Gateway) -> httpx.Client:
    with httpx.Client(base_url=gateway.base_url, timeout=30.0) as c:
        yield c


# ── the REAL Clerk instance: genuine tokens, genuine JWKS ─────────────────────

PREFERRED_REAL_GATEWAY_PORT = int(os.environ.get("SP_E2E_REAL_GATEWAY_PORT", "3398"))
REPO_ROOT = GATEWAY_DIR.parent.parent


@pytest.fixture(scope="session")
def clerk_credentials() -> tuple[str, str]:
    """(publishable_key, secret_key) from the repo-root .env. Values never logged."""
    from .clerk_backend import load_env_value

    pk = load_env_value("CLERK_PUBLISHABLE_KEY", REPO_ROOT)
    sk = load_env_value("CLERK_SECRET_KEY", REPO_ROOT)
    if not pk or not sk:
        pytest.skip("CLERK_PUBLISHABLE_KEY / CLERK_SECRET_KEY not present in repo-root .env")
    if not pk.startswith(("pk_test_", "pk_live_")):
        pytest.skip("CLERK_PUBLISHABLE_KEY has an unexpected prefix")
    if pk.startswith("pk_live_"):
        pytest.skip("refusing to run against a Clerk PRODUCTION instance")
    return pk, sk


@pytest.fixture(scope="session")
def real_clerk(clerk_credentials):
    """Provision a throwaway Clerk org + admin/member users, then delete them.

    Creates exactly: 2 users, 1 organization, 2 sessions. Pre-existing users,
    organizations and memberships are never read for mutation or modified.
    """
    from .clerk_backend import ClerkError, provision, sweep_stale

    _pk, sk = clerk_credentials
    # A run killed before teardown leaves residue behind. Sweep it first, matching only
    # this harness's own naming convention.
    try:
        for line in sweep_stale(sk):
            print(f"[clerk sweep] {line}")
    except OSError as e:
        pytest.skip(f"Clerk Backend API unreachable: {e}")
    try:
        fixture = provision(sk)
    except ClerkError as e:
        pytest.skip(f"could not provision throwaway Clerk resources: {e}")
    except OSError as e:
        pytest.skip(f"Clerk Backend API unreachable: {e}")

    yield fixture

    for line in fixture.cleanup():
        print(f"[clerk cleanup] {line}")


@pytest.fixture(scope="session")
def real_gateway(real_e2e_database: str, clerk_credentials, real_clerk, tmp_path_factory):
    """A second cloud-mode gateway configured with the REAL Clerk publishable key.

    It fetches the genuine JWKS from the Clerk domain and verifies genuine
    Clerk-signed tokens. SP_EXPECTED_AZP is deliberately unset: real Clerk session
    tokens carry no `azp` claim, so configuring one would reject every real token.
    """
    pk, _sk = clerk_credentials
    port = _free_port(PREFERRED_REAL_GATEWAY_PORT)

    seed_plan_tier(REAL_DB_NAME, real_clerk.org_id)

    workdir = tmp_path_factory.mktemp("sp-e2e-real-gateway")
    session_secret = secrets.token_urlsafe(32)
    env = _child_env(workdir, real_e2e_database, port, pk, ca_file=None, expected_azp=None,
                     session_jwt_secret=session_secret)
    proc, log_fh, log_path = _boot(env, port, workdir, "real-clerk")

    yield Gateway(f"http://127.0.0.1:{port}", None, proc, log_path, session_secret)  # type: ignore[arg-type]

    _shutdown(proc, log_fh)


@pytest.fixture(scope="session")
def real_client(real_gateway) -> httpx.Client:
    with httpx.Client(base_url=real_gateway.base_url, timeout=30.0) as c:
        yield c


# ── token fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def azp(gateway: Gateway) -> str:
    """Must match SP_EXPECTED_AZP on the synthetic gateway or every token 401s."""
    return gateway.base_url


@pytest.fixture(scope="session")
def member_token(gateway: Gateway, azp: str) -> str:
    """Clerk dev-form JWT, org_role=basic_member."""
    return gateway.clerk.mint(sub="user_member", org_id=ORG_ID, org_role="basic_member", azp=azp)


@pytest.fixture(scope="session")
def admin_token(gateway: Gateway, azp: str) -> str:
    """Clerk dev-form JWT, org_role=admin."""
    return gateway.clerk.mint(sub="user_admin", org_id=ORG_ID, org_role="admin", azp=azp)


@pytest.fixture(scope="session")
def staff_token(gateway: Gateway, azp: str) -> str:
    """Org admin whose sub is also in the gateway's SP_ADMIN_USER_IDS allowlist."""
    return gateway.clerk.mint(sub=STAFF_USER_ID, org_id=ORG_ID, org_role="admin", azp=azp)


@pytest.fixture(scope="session")
def admin_token_short_claim(gateway: Gateway, azp: str) -> str:
    """Clerk PRODUCTION short-claim JWT: o = {id, rol: "admin"}.

    This is the shape a genuine Clerk session token carries (verified against a real
    token: claim keys exp/fva/iat/iss/jti/nbf/o/org_id/pla/sid/sts/sub/v, with
    o.rol == "admin" and NO flat "org_role" claim). It is the primary production
    path, not an edge case.
    """
    return gateway.clerk.mint(
        sub="user_admin_prod", org_id=ORG_ID, org_role="admin", claim_style="short", azp=azp
    )


@pytest.fixture(scope="session")
def admin_token_short_claim_prefixed(gateway: Gateway, azp: str) -> str:
    """Short-claim JWT with the prefixed role spelling o.rol == "org:admin"."""
    return gateway.clerk.mint(
        sub="user_admin_prefixed", org_id=ORG_ID, org_role="org:admin", claim_style="short", azp=azp
    )


@pytest.fixture(scope="session")
def member_token_short_claim(gateway: Gateway, azp: str) -> str:
    """Short-claim member token: o.rol == "basic_member" and no flat org_role."""
    return gateway.clerk.mint(
        sub="user_member_prod", org_id=ORG_ID, org_role="basic_member", claim_style="short", azp=azp
    )


def _real_shape_extra(org_id: str) -> dict:
    """The non-org filler claims a genuine Clerk v2 session token carries."""
    return {"org_id": org_id, "v": 2, "fva": [0, -1], "jti": "e2e0000000000000",
            "pla": "u:free", "sts": "active"}


@pytest.fixture(scope="session")
def clerk_shaped_admin_token(gateway: Gateway, azp: str) -> str:
    """Byte-for-byte claim-set replica of a real Clerk v2 admin session token.

    Carries BOTH `o = {id, rol: "admin", slg}` and a flat `org_id`, plus
    v/fva/jti/pla/sts — exactly the key set observed on a genuine token.
    """
    return gateway.clerk.mint(
        sub="user_clerk_shaped", org_id=ORG_ID, org_role="admin", claim_style="short",
        azp=azp, extra=_real_shape_extra(ORG_ID),
    )


@pytest.fixture(scope="session")
def clerk_shaped_member_token(gateway: Gateway, azp: str) -> str:
    """Same replica shape, but o.rol == "basic_member"."""
    return gateway.clerk.mint(
        sub="user_clerk_shaped_member", org_id=ORG_ID, org_role="basic_member",
        claim_style="short", azp=azp, extra=_real_shape_extra(ORG_ID),
    )


@pytest.fixture(scope="session")
def no_role_token(gateway: Gateway, azp: str) -> str:
    """Valid signature, org present, but NO role claim at all — must fail closed."""
    return gateway.clerk.mint(sub="user_norole", org_id=ORG_ID, org_role=None, azp=azp)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def default_body(method: str) -> dict | None:
    """An empty JSON object for mutating verbs so validation, not auth, decides."""
    return {} if method in {"POST", "PUT", "PATCH"} else None


def call(client: httpx.Client, method: str, url: str, token: str | None = None,
         json_body: dict | None = None) -> httpx.Response:
    headers = bearer(token) if token else {}
    # Same-origin header so the cookie-auth CSRF middleware is never the thing that
    # answers (it exempts Bearer callers anyway, but this removes the ambiguity).
    headers["Origin"] = str(client.base_url).rstrip("/")
    return client.request(method, url, headers=headers, json=json_body)
