"""Two real gateway processes, one database, one upload quota.

The quota used to live in a process-local dict, so every uvicorn worker enforced
its own private copy of the limit. These tests boot two independent uvicorn
processes against the same throwaway database and assert the ceiling is shared;
when MinIO is reachable they also push a >64 MB multipart upload end to end
through one of them, which is the only way to confirm the per-part
ContentLength binding still holds against a real S3 API.

Skips cleanly (never fails) without docker, Postgres, or uvicorn. Boots are
sequential on purpose: init_db() takes ACCESS EXCLUSIVE locks for its
ADD COLUMN IF NOT EXISTS sweep, so a second gateway starting while the first is
still initialising the same database would block on a relation lock.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

GATEWAY_DIR = Path(__file__).resolve().parents[1]

DB_CONTAINER = "signalpilot-db-1"
DB_HOST = "127.0.0.1"
DB_PORT = 5601
DB_USER = "signalpilot"
DB_NAME = "sp_e2e_upload_quota"

S3_ENDPOINT = os.environ.get("SP_TEST_S3_ENDPOINT", "http://127.0.0.1:9000")
S3_BUCKET = "sp-eval-uploads"
S3_KEY = "minioadmin"

PREFERRED_PORTS = (3395, 3396)
BOOT_TIMEOUT_SECONDS = 150

MB = 1024 * 1024
PART_SIZE = 64 * MB
MAX_OPEN = 3  # gateway.api.uploads._MAX_OPEN_UPLOADS_PER_USER


def _free_port(preferred: int) -> int:
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
    """Read the throwaway dev database password from docker-compose.yml.

    Handed to the child process env only — never logged or reported.
    """
    compose = GATEWAY_DIR.parent.parent / "docker-compose.yml"
    if compose.exists():
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


def _require_db_container() -> None:
    if _docker() is None:
        pytest.skip("docker CLI not available")
    probe = subprocess.run([_docker(), "inspect", "-f", "{{.State.Running}}", DB_CONTAINER],
                           capture_output=True, text=True)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        pytest.skip(f"container {DB_CONTAINER} is not running")


def _fresh_database() -> str:
    """Drop and recreate the throwaway database. Never touches `signalpilot`."""
    assert DB_NAME.startswith("sp_e2e"), f"refusing to drop non-e2e database {DB_NAME!r}"
    _psql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
          f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid();")
    _psql(f"DROP DATABASE IF EXISTS {DB_NAME};")
    created = _psql(f"CREATE DATABASE {DB_NAME};")
    if created.returncode != 0:
        pytest.skip(f"could not create {DB_NAME}: {created.stderr.strip()[:200]}")
    return f"postgresql://{DB_USER}:{_db_password()}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def _child_env(workdir: Path, database_url: str) -> dict[str, str]:
    """Child environment from an explicit OS-plumbing allowlist — no developer
    credential from the shell or repo .env reaches the gateway under test."""
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

        "SP_DEPLOYMENT_MODE": "local",
        "DATABASE_URL": database_url,

        # Eval uploads pointed at the local MinIO.
        "SP_EVAL_UPLOADS_BUCKET": S3_BUCKET,
        "SP_EVAL_UPLOADS_S3_ENDPOINT": S3_ENDPOINT,
        "SP_EVAL_UPLOADS_S3_PUBLIC_ENDPOINT": S3_ENDPOINT,
        "SP_EVAL_UPLOADS_S3_ACCESS_KEY": S3_KEY,
        "SP_EVAL_UPLOADS_S3_SECRET_KEY": S3_KEY,
        "SP_EVAL_UPLOADS_S3_REGION": "us-east-1",
        "SP_EVAL_UPLOADS_MAX_MB": "500",

        # Keep background machinery inert.
        "SP_DBT_PROXY_ENABLED": "false",
        "SP_RATE_LIMIT_ENABLED": "false",
        "SP_BYOK_PROVIDER": "local",
        "SP_GIT_REPOS_DIR": str(workdir / "repos"),
        "SP_DATA_DIR": str(workdir / "data"),
    }
    return env


def _boot(env: dict[str, str], port: int, workdir: Path, label: str):
    """Launch uvicorn and wait for /health. pytest.skip on failure, never fail."""
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
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=3).status_code < 500:
                return proc, log_fh
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    pytest.skip(f"[{label}] gateway not healthy in {BOOT_TIMEOUT_SECONDS}s:\n{tail()}")


def _shutdown(proc: subprocess.Popen, log_fh) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        try:
            log_fh.close()
        except Exception:  # pragma: no cover
            pass


@pytest.fixture(scope="module")
def workers(tmp_path_factory) -> tuple[str, str]:
    """Two gateway processes sharing one database. Yields their base URLs."""
    _require_db_container()
    database_url = _fresh_database()
    workdir = tmp_path_factory.mktemp("upload-quota-workers")
    env = _child_env(workdir, database_url)

    booted = []
    try:
        for index, preferred in enumerate(PREFERRED_PORTS):
            port = _free_port(preferred)
            proc, log_fh = _boot(env, port, workdir, f"w{index}")
            booted.append((f"http://127.0.0.1:{port}", proc, log_fh))
        yield tuple(url for url, _, _ in booted)
    finally:
        for _, proc, log_fh in booted:
            _shutdown(proc, log_fh)


@pytest.fixture
def clean_quota(workers):
    _psql("DELETE FROM gateway_upload_sessions;", database=DB_NAME)
    yield workers
    _psql("DELETE FROM gateway_upload_sessions;", database=DB_NAME)


async def _initiate(client: httpx.AsyncClient, base_url: str, size_bytes: int) -> httpx.Response:
    return await client.post(
        f"{base_url}/api/evals/upload/initiate",
        json={"filename": "multiworker.zip", "size_bytes": size_bytes},
        timeout=60,
    )


@pytest.mark.asyncio
async def test_quota_filled_on_one_worker_is_seen_by_the_other(clean_quota):
    worker_a, worker_b = clean_quota
    async with httpx.AsyncClient() as client:
        for _ in range(MAX_OPEN):
            resp = await _initiate(client, worker_a, 10)
            assert resp.status_code == 200, resp.text

        resp = await _initiate(client, worker_b, 10)
        assert resp.status_code == 429, resp.text
        assert "uploads in progress" in resp.text.lower()


@pytest.mark.asyncio
async def test_simultaneous_initiations_across_workers_share_one_ceiling(clean_quota):
    """A burst split across both processes still admits only MAX_OPEN."""
    workers_ = clean_quota
    async with httpx.AsyncClient() as client:
        responses = await asyncio.gather(
            *[_initiate(client, workers_[i % 2], 10) for i in range(12)]
        )
    statuses = [r.status_code for r in responses]
    assert statuses.count(200) == MAX_OPEN
    assert statuses.count(429) == 12 - MAX_OPEN


@pytest.mark.asyncio
async def test_byte_ceiling_is_shared_across_workers(clean_quota):
    """500 MB cap, 300 MB per upload: the second must be refused by worker B."""
    worker_a, worker_b = clean_quota
    async with httpx.AsyncClient() as client:
        first = await _initiate(client, worker_a, 300 * MB)
        assert first.status_code == 200, first.text
        second = await _initiate(client, worker_b, 300 * MB)
        assert second.status_code == 429, second.text
        assert "reserve" in second.text.lower()


@pytest.mark.asyncio
async def test_large_multipart_upload_round_trips_through_minio(clean_quota):
    """>64 MB upload end to end: each presigned part is bound to its exact length."""
    worker_a, _ = clean_quota
    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_KEY,
            aws_secret_access_key=S3_KEY,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
        )
        try:
            s3.head_bucket(Bucket=S3_BUCKET)
        except Exception:
            s3.create_bucket(Bucket=S3_BUCKET)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"MinIO not reachable at {S3_ENDPOINT}: {exc}")

    size = PART_SIZE + MB  # 65 MB → two parts
    payload = b"PK" + os.urandom(size - 2)

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await _initiate(client, worker_a, size)
        assert resp.status_code == 200, resp.text
        plan = resp.json()
        assert len(plan["part_urls"]) == 2

        # The signature pins Content-Length: a part of the wrong size is rejected.
        short = await client.put(plan["part_urls"][0], content=payload[:1024])
        assert short.status_code >= 400

        etags = []
        for n, (url, (start, end)) in enumerate(
            zip(plan["part_urls"], [(0, PART_SIZE), (PART_SIZE, size)], strict=True), start=1
        ):
            put = await client.put(url, content=payload[start:end])
            assert put.status_code == 200, put.text
            etags.append({"part_number": n, "etag": put.headers["ETag"].strip('"')})

        done = await client.post(
            f"{worker_a}/api/evals/upload/complete",
            json={"key": plan["key"], "upload_id": plan["upload_id"], "parts": etags},
            timeout=180,
        )
        assert done.status_code == 200, done.text

    head = s3.head_object(Bucket=S3_BUCKET, Key=plan["key"])
    assert head["ContentLength"] == size
    s3.delete_object(Bucket=S3_BUCKET, Key=plan["key"])
