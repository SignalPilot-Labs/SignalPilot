"""dbt executor: in-sandbox SSH tunnel for bastion-fronted warehouses."""

from __future__ import annotations

import json
import logging
import sys
import types
from dataclasses import dataclass, field

import pytest

from gateway.sandbox_runtime.base import ExecResult
from gateway.standalone_chat import dbt_executor, dbt_tunnel
from gateway.standalone_chat.dbt_executor import DbtExecutorError
from gateway.standalone_chat.dbt_tunnel import (
    FORWARDER_SCRIPT,
    TUNNEL_CONFIG_PATH,
    TUNNEL_LOG_PATH,
    TUNNEL_READY_PATH,
    TUNNEL_SCRIPT_PATH,
    DbtTunnelError,
    ensure_tunnel_alive,
    plan_tunnel,
    start_tunnel,
)

FAKE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nSECRETKEYMATERIAL\n-----END OPENSSH PRIVATE KEY-----\n"
PG_DSN = "postgresql://dbuser:dbpass@warehouse.internal:5433/analytics?sslmode=require"


def key_tunnel(**overrides) -> dict:
    cfg = {
        "enabled": True,
        "host": "bastion.example.com",
        "port": 2222,
        "username": "jump",
        "auth_method": "key",
        "private_key": FAKE_KEY,
        "private_key_passphrase": "hunter2",
    }
    cfg.update(overrides)
    return cfg


# ── fake runtime ─────────────────────────────────────────────────────────────


@dataclass
class FakeRuntime:
    """Minimal SandboxRuntime stand-in. ``ready_after`` controls how many
    ready-file probes fail before the file appears (None = never)."""

    ready_after: int | None = 0
    liveness_ok: bool = True
    files: dict[str, bytes] = field(default_factory=dict)
    commands: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)
    destroyed: list[str] = field(default_factory=list)
    _probes: int = 0

    async def create(self, spec) -> str:
        return "sbx_exec"

    async def destroy(self, sandbox_id: str) -> None:
        self.destroyed.append(sandbox_id)

    async def write_file(self, sandbox_id: str, path: str, content: bytes) -> None:
        self.files[path] = content

    async def read_file(self, sandbox_id: str, path: str) -> bytes | None:
        return self.files.get(path)

    async def start_process(self, sandbox_id: str, command: str, **kw) -> str:
        self.processes.append(command)
        self.files.pop(TUNNEL_READY_PATH, None)
        self.files[TUNNEL_LOG_PATH] = b"sp_tunnel: could not parse SSH private key (supported formats: RSA)\n"
        return f"proc_{len(self.processes)}"

    async def exec(self, sandbox_id: str, command: str, **kw) -> ExecResult:
        self.commands.append(command)
        if command.startswith(f"cat {TUNNEL_READY_PATH}"):
            self._probes += 1
            if self.ready_after is not None and self._probes > self.ready_after:
                self.files[TUNNEL_READY_PATH] = b"READY 15432\n"
            data = self.files.get(TUNNEL_READY_PATH)
            if data is None:
                return ExecResult(1, "", "cat: no such file")
            return ExecResult(0, data.decode(), "")
        if command.startswith("grep -q '^READY'"):
            return ExecResult(0 if self.liveness_ok else 1, "", "")
        return ExecResult(0, "", "")


@pytest.fixture()
def fast_ready(monkeypatch):
    monkeypatch.setattr(dbt_tunnel, "_READY_TIMEOUT_SECONDS", 0.4)
    monkeypatch.setattr(dbt_tunnel, "_READY_POLL_SECONDS", 0.02)


# ── plan_tunnel ──────────────────────────────────────────────────────────────


def test_no_tunnel_leaves_dsn_untouched():
    assert plan_tunnel("postgres", PG_DSN, None) is None
    assert plan_tunnel("postgres", PG_DSN, {}) is None
    assert plan_tunnel("postgres", PG_DSN, {"ssh_tunnel": key_tunnel(enabled=False)}) is None


def test_plan_rewrites_dsn_to_local_forward_and_keeps_remote():
    plan = plan_tunnel("postgres", PG_DSN, {"ssh_tunnel": key_tunnel()})
    assert plan is not None
    assert plan.local_port == 15432
    assert plan.remote_host == "warehouse.internal" and plan.remote_port == 5433
    assert plan.dsn == "postgresql://dbuser:dbpass@127.0.0.1:15432/analytics?sslmode=require"
    m = plan.material
    assert (m["ssh_host"], m["ssh_port"], m["ssh_username"]) == ("bastion.example.com", 2222, "jump")
    assert m["private_key"] == FAKE_KEY and m["private_key_passphrase"] == "hunter2"
    assert m["proxy_command"] is None
    # Secrets never surface through repr.
    assert FAKE_KEY.strip() not in repr(plan) and "hunter2" not in repr(plan)


def test_plan_mssql_uses_its_own_local_port():
    plan = plan_tunnel("mssql", "mssql://admin:pw@sql.internal/Analytics", {"ssh_tunnel": key_tunnel()})
    assert plan.local_port == 11433 and plan.remote_port == 1433
    assert plan.dsn.startswith("mssql://admin:pw@127.0.0.1:11433/")


def test_plan_builds_validated_proxy_command():
    plan = plan_tunnel(
        "postgres", PG_DSN, {"ssh_tunnel": key_tunnel(proxy_host="proxy.corp", proxy_port=3128)}
    )
    assert plan.material["proxy_command"] == "socat - PROXY:proxy.corp:bastion.example.com:2222,proxyport=3128"
    with pytest.raises(DbtTunnelError, match="rejected"):
        plan_tunnel("postgres", PG_DSN, {"ssh_tunnel": key_tunnel(proxy_host="evil,EXEC:sh")})


def test_plan_rejects_unsupported_db_type():
    with pytest.raises(DbtTunnelError, match="not supported for 'snowflake'"):
        plan_tunnel("snowflake", "snowflake://u:p@acct/db", {"ssh_tunnel": key_tunnel()})


def test_plan_rejects_agent_auth():
    with pytest.raises(DbtTunnelError, match="agent"):
        plan_tunnel("postgres", PG_DSN, {"ssh_tunnel": key_tunnel(auth_method="agent", private_key=None)})


@pytest.mark.parametrize(
    "overrides",
    [{"auth_method": "key", "private_key": None}, {"auth_method": "password"}, {"host": None}],
)
def test_plan_rejects_incomplete_material(overrides):
    with pytest.raises(DbtTunnelError):
        plan_tunnel("postgres", PG_DSN, {"ssh_tunnel": key_tunnel(**overrides)})


# ── start_tunnel / ensure_tunnel_alive ───────────────────────────────────────


@pytest.mark.asyncio
async def test_start_tunnel_writes_material_and_script_without_logging_secrets(fast_ready, caplog):
    rt = FakeRuntime(ready_after=1)
    plan = plan_tunnel("postgres", PG_DSN, {"ssh_tunnel": key_tunnel()})
    with caplog.at_level(logging.DEBUG, logger="gateway.standalone_chat.dbt_tunnel"):
        await start_tunnel(rt, "sbx", plan)

    material = json.loads(rt.files[TUNNEL_CONFIG_PATH])
    assert material["private_key"] == FAKE_KEY
    assert (material["remote_host"], material["remote_port"], material["local_port"]) == (
        "warehouse.internal", 5433, 15432,
    )
    assert rt.files[TUNNEL_SCRIPT_PATH].decode() == FORWARDER_SCRIPT
    assert any("pip install --quiet sshtunnel paramiko" in c for c in rt.commands)
    assert any(f"chmod 600 {TUNNEL_CONFIG_PATH}" in c for c in rt.commands)
    assert len(rt.processes) == 1
    assert "/opt/sp-notebook/.venv/bin/python /creds/sp_tunnel.py" in rt.processes[0]
    assert f">{TUNNEL_LOG_PATH} 2>&1" in rt.processes[0]
    logged = caplog.text
    assert "SECRETKEYMATERIAL" not in logged and "hunter2" not in logged and "dbpass" not in logged
    assert "bastion.example.com" in logged


@pytest.mark.asyncio
async def test_ready_timeout_raises_with_forwarder_output(fast_ready):
    rt = FakeRuntime(ready_after=None)
    plan = plan_tunnel("postgres", PG_DSN, {"ssh_tunnel": key_tunnel()})
    with pytest.raises(DbtTunnelError) as exc:
        await start_tunnel(rt, "sbx", plan)
    assert "did not come up" in str(exc.value)
    assert "could not parse SSH private key" in str(exc.value)


@pytest.mark.asyncio
async def test_ensure_tunnel_alive_relaunches_only_when_down(fast_ready):
    rt = FakeRuntime(ready_after=0, liveness_ok=True)
    assert await ensure_tunnel_alive(rt, "sbx", 15432) is False
    assert rt.processes == []
    rt.liveness_ok = False
    assert await ensure_tunnel_alive(rt, "sbx", 15432) is True
    assert len(rt.processes) == 1
    assert any("/dev/tcp/127.0.0.1/15432" in c for c in rt.commands)


# ── ensure_executor integration ──────────────────────────────────────────────


class FakeStore:
    def __init__(self, extras: dict | None):
        self.extras = extras

    async def get_connection_string(self, name):
        return PG_DSN

    async def get_connection(self, name):
        return types.SimpleNamespace(db_type="DBType.postgres")

    async def get_workspace_project(self, project_id):
        return None

    async def get_credential_extras(self, name):
        return self.extras or {}


class FakeWorkspaceStore:
    def __init__(self, storage):
        pass

    async def build_snapshot(self, db, **kw):
        return 7, "snap/key"

    async def load_manifest(self, db, **kw):
        return {}


@pytest.fixture()
def executor_env(monkeypatch, fast_ready):
    rt = FakeRuntime(ready_after=0)
    storage = types.SimpleNamespace(enabled=True)

    async def presign(key, expires_seconds=0):
        return "https://snapshot"

    storage.presign_get = presign
    monkeypatch.setattr(dbt_executor, "workspace_object_storage", lambda: storage)
    monkeypatch.setattr(dbt_executor, "WorkspaceStore", FakeWorkspaceStore)
    monkeypatch.setattr(dbt_executor, "resolve_dbt_project_dir_detailed", lambda s, m: ("dbt", "manifest", None))

    async def profile_name(*a, **kw):
        return "demo"

    monkeypatch.setattr(dbt_executor, "_read_profile_name", profile_name)
    monkeypatch.setattr(dbt_executor, "get_sandbox_runtime", lambda: rt)
    monkeypatch.setattr(
        dbt_executor, "get_sandbox_runtime_settings", lambda: types.SimpleNamespace(time_limit_seconds=900)
    )
    monkeypatch.setattr(dbt_executor, "get_notebook_settings", lambda: types.SimpleNamespace(vercel_image=None))
    monkeypatch.setattr(dbt_executor, "_executors", {})
    monkeypatch.setattr(dbt_executor, "_executor_seen", {})
    monkeypatch.setattr(dbt_executor, "_executor_tunnels", {})
    return rt


async def _ensure(store):
    return await dbt_executor.ensure_executor(
        None, identity="chat:abc12345-1", org_id="o", project_id="p", branch="main",
        connection_name="pg", store=store,
    )


@pytest.mark.asyncio
async def test_executor_without_tunnel_targets_real_host(executor_env):
    rt = executor_env
    await _ensure(FakeStore(None))
    profile = rt.files["/creds/profiles.yml"].decode()
    assert "host: warehouse.internal" in profile and "port: 5433" in profile
    assert TUNNEL_CONFIG_PATH not in rt.files and rt.processes == []
    assert dbt_executor._executor_tunnels == {}


@pytest.mark.asyncio
async def test_executor_with_tunnel_targets_local_forward_and_rechecks_on_reuse(executor_env):
    rt = executor_env
    store = FakeStore({"ssh_tunnel": key_tunnel()})
    sandbox_id, dbt_dir, schema = await _ensure(store)
    profile = rt.files["/creds/profiles.yml"].decode()
    assert "host: 127.0.0.1" in profile and "port: 15432" in profile
    assert "warehouse.internal" not in profile
    assert "password: dbpass" in profile  # warehouse credentials still flow to dbt
    assert json.loads(rt.files[TUNNEL_CONFIG_PATH])["private_key"] == FAKE_KEY
    assert dbt_executor._executor_tunnels == {"chat:abc12345-1": 15432}
    assert len(rt.processes) == 1

    # Reuse: forwarder dead => relaunched from the material already in /creds.
    rt.liveness_ok = False
    again = await _ensure(store)
    assert again[0] == sandbox_id
    assert len(rt.processes) == 2

    await dbt_executor.release_executor("chat:abc12345-1")
    assert dbt_executor._executor_tunnels == {} and rt.destroyed == [sandbox_id]


@pytest.mark.asyncio
async def test_executor_tunnel_failure_is_a_dbt_executor_error_and_destroys_sandbox(executor_env):
    rt = executor_env
    rt.ready_after = None
    with pytest.raises(DbtExecutorError, match="did not come up"):
        await _ensure(FakeStore({"ssh_tunnel": key_tunnel()}))
    assert rt.destroyed == ["sbx_exec"]
    assert dbt_executor._executors == {}


@pytest.mark.asyncio
async def test_executor_rejects_agent_auth_before_creating_sandbox(executor_env):
    with pytest.raises(DbtExecutorError, match="agent"):
        await _ensure(FakeStore({"ssh_tunnel": key_tunnel(auth_method="agent", private_key=None)}))
    assert executor_env.destroyed == []


# ── forwarder script (exec'd with paramiko/sshtunnel mocked) ─────────────────


class _Key:
    calls: list = []

    @classmethod
    def from_private_key(cls, fh, password=None):
        cls.calls.append((cls.__name__, fh.read(), password))
        if cls.__name__ != "Ed25519Key":
            raise ValueError("not this key type")
        return cls()


class RSAKey(_Key): ...


class Ed25519Key(_Key): ...


class ECDSAKey(_Key): ...


class FakeForwarder:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture()
def forwarder_ns(monkeypatch):
    _Key.calls = []
    paramiko = types.ModuleType("paramiko")
    paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey = RSAKey, Ed25519Key, ECDSAKey
    paramiko.ProxyCommand = lambda cmd: ("proxy", cmd)
    sshtunnel = types.ModuleType("sshtunnel")
    sshtunnel.SSHTunnelForwarder = FakeForwarder
    monkeypatch.setitem(sys.modules, "paramiko", paramiko)
    monkeypatch.setitem(sys.modules, "sshtunnel", sshtunnel)
    ns: dict = {"__name__": "sp_tunnel_under_test"}
    exec(compile(FORWARDER_SCRIPT, "sp_tunnel.py", "exec"), ns)
    return ns


def _material(**overrides):
    m = dict(plan_tunnel("postgres", PG_DSN, {"ssh_tunnel": key_tunnel()}).material)
    m.update(overrides)
    return m


def test_forwarder_script_builds_key_tunnel_with_fixed_bind(forwarder_ns):
    fwd = forwarder_ns["build"](_material())
    kw = fwd.kwargs
    assert kw["ssh_address_or_host"] == ("bastion.example.com", 2222)
    assert kw["remote_bind_address"] == ("warehouse.internal", 5433)
    assert kw["local_bind_address"] == ("127.0.0.1", 15432)
    assert kw["set_keepalive"] == 60 and isinstance(kw["ssh_pkey"], Ed25519Key)
    # RSA tried first, then Ed25519 (which succeeded); ECDSA never reached.
    assert [c[0] for c in _Key.calls] == ["RSAKey", "Ed25519Key"]
    assert _Key.calls[0][1] == FAKE_KEY and _Key.calls[0][2] == "hunter2"


def test_forwarder_script_password_and_agent_paths(forwarder_ns):
    fwd = forwarder_ns["build"](_material(auth_method="password", password="pw", private_key=None))
    assert fwd.kwargs["ssh_password"] == "pw" and "ssh_pkey" not in fwd.kwargs
    with pytest.raises(SystemExit):
        forwarder_ns["build"](_material(auth_method="agent"))


def test_forwarder_script_proxy_requires_socat(forwarder_ns, monkeypatch):
    material = _material(proxy_command="socat - PROXY:proxy.corp:bastion.example.com:2222,proxyport=3128")
    monkeypatch.setattr(forwarder_ns["shutil"], "which", lambda name: None)
    with pytest.raises(SystemExit):
        forwarder_ns["build"](material)
    monkeypatch.setattr(forwarder_ns["shutil"], "which", lambda name: "/usr/bin/socat")
    fwd = forwarder_ns["build"](material)
    assert fwd.kwargs["ssh_proxy"] == ("proxy", material["proxy_command"])


def test_forwarder_script_stays_small():
    assert len(FORWARDER_SCRIPT.strip().splitlines()) <= 80
