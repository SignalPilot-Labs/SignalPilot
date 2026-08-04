"""Read-only introspection of live eval sandboxes (the /evals sandbox panel).

backends.py owns the write side: creating, waiting on and deleting the
container that runs one eval question. This is the read side: what is alive
right now, why a pod that is not Running is not Running, and a bounded live tail
of its output. Nothing here mutates cluster or daemon state.

Org scoping differs by backend and both are enforced here:

    kubernetes  the per-org namespace, which is also the only namespace the
                gateway's RoleBinding lets it read
    docker      no namespaces exist, so a container is visible only when the
                run id in its labels resolves to a run under the caller's own
                eval root

Nothing that could carry a credential is emitted. Pod/container specs are never
returned (that is where env lives); free text that a cluster can put in front of
us: event messages, container state messages: goes through `redact` first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import unquote, urlsplit

import httpx

from ..config.evals import EvalRunSettings, get_eval_run_settings
from . import runner
from .backends import _DOCKER_API, _EVAL_POD_LABEL

logger = logging.getLogger(__name__)

# Bounds every live stream carries regardless of who is watching.
LOG_STREAM_MAX_BYTES = 2_000_000
LOG_STREAM_MAX_SECONDS = 1800

_POD_LABEL_SELECTOR = f"{_EVAL_POD_LABEL}=1"
_DOCKER_LABEL = "signalpilot.eval"

_SANDBOX_NAME_RE = re.compile(r"^(?:sp-eval-[0-9a-f]{6,32}|[0-9a-f]{12,64})$")


def is_valid_sandbox_name(name: str) -> bool:
    """Names this module will accept from a URL path.

    Covers both what the backends mint: `sp-eval-<hex>` pod names and Docker's
    hex container ids. Anything else is refused before it reaches an API call.
    """
    return bool(_SANDBOX_NAME_RE.fullmatch(name or ""))


# Redaction.

REDACTED = "[redacted]"

# Shapes that must never survive into a response even when the exact value is
# not known to this process (the per-run MCP key, for instance, is minted by the
# route that started the run and is gone by the time anyone watches).
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}")
_SP_TOKEN = re.compile(r"\bsp_[0-9a-f]{32}\b")
_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*(?:bearer\s+)?[^\s'\"<>]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s'\"<>]+")
_API_KEY_HEADER = re.compile(r"(?i)\b(x-api-key)\s*[:=]\s*[^\s'\"<>]+")
_ENV_SECRET = re.compile(
    r"(?i)\b(PGPASSWORD|DATABASE_URL|SP_API_KEY|ANTHROPIC_API_KEY|"
    r"CLAUDE_CODE_OAUTH_TOKEN|GITHUB_TOKEN|GH_TOKEN|AWS_SECRET_ACCESS_KEY|"
    r"AWS_SESSION_TOKEN)\s*[:=]\s*[^\s'\"<>]+"
)
_SIGNED_URL_SECRET = re.compile(
    r"(?i)([?&](?:X-Amz-(?:Credential|Signature|Security-Token)|AWSAccessKeyId|Signature)=)"
    r"[^&\s'\"<>]+"
)
_BLOB = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])")
_DSN_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^:/@\s]+:[^@\s]+@")


def _redact_blob(match: re.Match[str]) -> str:
    # An all-hex run is an image digest or a container id, not a credential:
    # redacting those would hide exactly what a pull failure needs to show.
    return match.group(0) if re.fullmatch(r"[0-9a-f]+", match.group(0)) else REDACTED


def redact(text: str, *, extra_secrets: Iterable[str] = ()) -> str:
    """Strip credentials from text the cluster or daemon hands us."""
    if not text:
        return ""
    try:
        settings = get_eval_run_settings()
        known = [settings.claude_token, settings.anthropic_key]
    except Exception:
        known = []
    secrets = [*known, *extra_secrets]
    # Drivers often log only a DSN password rather than the complete URL.
    for value in list(secrets):
        if "://" not in value:
            continue
        try:
            password = urlsplit(value).password
        except ValueError:
            password = None
        if password:
            secrets.append(unquote(password))
    for value in secrets:
        if value and len(value) >= 8:
            text = text.replace(value, REDACTED)
    text = _AUTH_HEADER.sub(lambda m: f"{m.group(1)}: {REDACTED}", text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _API_KEY_HEADER.sub(lambda m: f"{m.group(1)}: {REDACTED}", text)
    text = _ENV_SECRET.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    text = _SIGNED_URL_SECRET.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    text = _SK_TOKEN.sub(REDACTED, text)
    text = _SP_TOKEN.sub(REDACTED, text)
    text = _DSN_USERINFO.sub(lambda m: f"{m.group(1)}{REDACTED}:{REDACTED}@", text)
    return _BLOB.sub(_redact_blob, text)


class _RedactionBuffer:
    """Keep a tail so credentials split across transport chunks stay intact."""

    _TAIL = 256

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, chunk: str) -> str:
        self._pending += chunk
        newline = self._pending.rfind("\n")
        if newline >= 0:
            ready, self._pending = self._pending[: newline + 1], self._pending[newline + 1 :]
            return redact(ready)
        if len(self._pending) > self._TAIL * 2:
            ready, self._pending = self._pending[: -self._TAIL], self._pending[-self._TAIL :]
            return redact(ready)
        return ""

    def flush(self) -> str:
        ready, self._pending = self._pending, ""
        return redact(ready)


# Shared shaping helpers.


def _iso(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _age_seconds(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(float(value), UTC)
    elif isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - moment).total_seconds()))


def _pick(d: dict, *names, default=None):
    """Read the first present key: kubernetes_asyncio `to_dict()` is snake_case
    but a raw manifest dict is camelCase, and tests feed both."""
    for name in names:
        if name in d and d[name] is not None:
            return d[name]
    return default


class SandboxView(Protocol):
    async def inventory(self) -> dict: ...
    async def events(self, name: str) -> dict: ...
    def stream_logs(self, name: str, *, tail_lines: int) -> AsyncIterator[tuple[str, str]]: ...
    async def aclose(self) -> None: ...


# Kubernetes.


class KubernetesSandboxView:
    """Pods, events and live logs for one org's eval namespace."""

    backend = "kubernetes"
    supports_live_logs = True

    def __init__(self, settings: EvalRunSettings, *, org_id: str) -> None:
        if not org_id:
            raise ValueError("org_id is required to read eval sandboxes")
        self._settings = settings
        self._org_id = org_id
        self._orchestrator = None
        self._namespace = ""

    async def aclose(self) -> None:
        if self._orchestrator is not None:
            await self._orchestrator.close()
            self._orchestrator = None

    async def _connect(self) -> tuple[object, str]:
        """(core api, namespace), or (None, "") when no cluster is reachable.

        Resolves the namespace without bootstrapping it: the panel is read-only,
        so an org that has never run an eval reports "no sandboxes", it does not
        provision a namespace as a side effect of someone opening a page.
        """
        if self._orchestrator is None:
            from ..orchestrator.kubernetes import KubernetesOrchestrator

            try:
                orch = KubernetesOrchestrator()
                await orch._ensure_client()
            except Exception as exc:
                logger.warning("Eval sandbox view: no Kubernetes client (%s)", exc)
                return None, ""
            if orch._core_api is None:
                return None, ""
            orch._namespace_prefix = self._settings.k8s_namespace_prefix
            self._orchestrator = orch
            self._namespace = orch._resolve_namespace(self._org_id)
        return self._orchestrator._core_api, self._namespace

    async def inventory(self) -> dict:
        core, ns = await self._connect()
        if core is None:
            return {
                "backend": self.backend,
                "live": False,
                "supports_live_logs": True,
                "namespace": "",
                "message": "No reachable Kubernetes cluster — sandbox introspection is unavailable.",
                "sandboxes": [],
            }
        owners = await runner.sandbox_index(self._org_id)
        try:
            resp = await core.list_namespaced_pod(
                namespace=ns, label_selector=_POD_LABEL_SELECTOR
            )
        except Exception as exc:
            # A namespace that does not exist yet is the normal "never ran an
            # eval here" case, not an error worth surfacing as a failure.
            if _is_not_found(exc):
                return _empty_inventory(self.backend, ns)
            logger.warning("Eval sandbox list failed in %s: %s", ns, exc)
            return {
                "backend": self.backend,
                "live": False,
                "supports_live_logs": True,
                "namespace": ns,
                "message": f"Could not list eval pods: {type(exc).__name__}",
                "sandboxes": [],
            }
        items = _as_dict(resp).get("items") or []
        return {
            "backend": self.backend,
            "live": True,
            "supports_live_logs": True,
            "namespace": ns,
            "message": "",
            "sandboxes": [_shape_pod(pod, owners) for pod in items],
        }

    async def events(self, name: str) -> dict:
        core, ns = await self._connect()
        if core is None:
            return {"backend": self.backend, "supported": True, "message": "No reachable Kubernetes cluster.", "events": []}
        try:
            resp = await core.list_namespaced_event(
                namespace=ns,
                field_selector=f"involvedObject.name={name},involvedObject.kind=Pod",
            )
        except Exception as exc:
            if _is_not_found(exc):
                return {"backend": self.backend, "supported": True, "message": "", "events": []}
            logger.warning("Eval sandbox events failed for %s/%s: %s", ns, name, exc)
            return {
                "backend": self.backend,
                "supported": True,
                "message": f"Could not read events: {type(exc).__name__}",
                "events": [],
            }
        events = [_shape_event(e) for e in (_as_dict(resp).get("items") or [])]
        events.sort(key=lambda e: e["last_seen"])
        return {"backend": self.backend, "supported": True, "message": "", "events": events[-50:]}

    async def stream_logs(self, name: str, *, tail_lines: int) -> AsyncIterator[tuple[str, str]]:
        core, ns = await self._connect()
        if core is None:
            yield "end", "no-cluster"
            return
        try:
            resp = await core.read_namespaced_pod_log(
                name=name,
                namespace=ns,
                container="eval",
                follow=True,
                tail_lines=tail_lines,
                _preload_content=False,
            )
        except Exception as exc:
            yield "error", f"could not attach to {name}: {type(exc).__name__}"
            yield "end", "attach-failed"
            return

        sent = 0
        redactor = _RedactionBuffer()
        deadline = asyncio.get_event_loop().time() + LOG_STREAM_MAX_SECONDS
        try:
            async for chunk in resp.content.iter_chunked(4096):
                text = chunk.decode("utf-8", errors="replace")
                sent += len(chunk)
                if safe := redactor.feed(text):
                    yield "log", safe
                if sent >= LOG_STREAM_MAX_BYTES:
                    if safe := redactor.flush():
                        yield "log", safe
                    yield "end", "byte-cap"
                    return
                if asyncio.get_event_loop().time() >= deadline:
                    if safe := redactor.flush():
                        yield "log", safe
                    yield "end", "deadline"
                    return
            # The API server closes the follow stream when the container exits.
            if safe := redactor.flush():
                yield "log", safe
            yield "end", "sandbox-exited"
        finally:
            _release(resp)


def _empty_inventory(backend: str, namespace: str) -> dict:
    return {
        "backend": backend,
        "live": True,
        "supports_live_logs": backend == "kubernetes",
        "namespace": namespace,
        "message": "",
        "sandboxes": [],
    }


def _is_not_found(exc: Exception) -> bool:
    text = str(exc)
    return "404" in text or "Not Found" in text or getattr(exc, "status", None) == 404


def _as_dict(resp) -> dict:
    return resp.to_dict() if hasattr(resp, "to_dict") else dict(resp)


def _release(resp) -> None:
    for attr in ("release", "close"):
        fn = getattr(resp, attr, None)
        if callable(fn):
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:
                pass
            return


def _container_state(status: dict) -> tuple[str, str, int, bool, bool]:
    """(reason, message, restart_count, ready, oom_killed) for the eval container.

    The reason is the field that separates "slow" from "broken":
    ContainerCreating and ImagePullBackOff are both non-Running, only one of
    them will ever finish.

    OOMKilled is called out separately because eval pods are sized like notebook
    pods (512Mi), which a heavy question: a dbt build, say: can exceed. The
    kubelet reports that as a terminated container with a non-zero exit code
    like any other crash, so without this flag "the agent failed" and "we did
    not give it enough memory" look identical in the panel.
    """
    statuses = _pick(status, "container_statuses", "containerStatuses", default=[]) or []
    for cs in statuses:
        state = cs.get("state") or {}
        waiting, running, terminated = state.get("waiting"), state.get("running"), state.get("terminated")
        restarts = int(_pick(cs, "restart_count", "restartCount", default=0) or 0)
        ready = bool(cs.get("ready"))
        # A container that OOMed and was restarted reports the kill under
        # last_state, not state, so both are checked.
        last_terminated = (_pick(cs, "last_state", "lastState", default={}) or {}).get("terminated") or {}
        if waiting:
            oom = str(last_terminated.get("reason") or "") == "OOMKilled"
            return str(waiting.get("reason") or "Waiting"), redact(str(waiting.get("message") or "")), restarts, ready, oom
        if terminated:
            reason = str(terminated.get("reason") or "Terminated")
            exit_code = _pick(terminated, "exit_code", "exitCode")
            message = redact(str(terminated.get("message") or ""))
            oom = reason == "OOMKilled" or str(last_terminated.get("reason") or "") == "OOMKilled"
            if oom and not message:
                message = "container exceeded its memory limit (SP_EVAL_MEMORY_LIMIT)"
            if exit_code is not None:
                message = f"exit {exit_code}{(' — ' + message) if message else ''}"
            return reason, message, restarts, ready, oom
        if running:
            oom = str(last_terminated.get("reason") or "") == "OOMKilled"
            return "Running", "", restarts, ready, oom
    pod_reason = _pick(status, "reason", default="")
    return str(pod_reason or "Pending"), redact(str(_pick(status, "message", default="") or "")), 0, False, False


def _shape_pod(pod: dict, owners: dict[str, dict]) -> dict:
    meta = pod.get("metadata") or {}
    status = pod.get("status") or {}
    spec = pod.get("spec") or {}
    name = str(meta.get("name") or "")
    labels = meta.get("labels") or {}
    reason, message, restarts, ready, oom_killed = _container_state(status)
    owner = owners.get(name, {})
    created = _pick(meta, "creation_timestamp", "creationTimestamp")
    return {
        "name": name,
        "backend": "kubernetes",
        "phase": str(status.get("phase") or "Unknown").lower(),
        "reason": reason,
        "message": message,
        "ready": ready,
        "oom_killed": oom_killed,
        "restart_count": restarts,
        "node": str(_pick(spec, "node_name", "nodeName", default="") or ""),
        "created_at": _iso(created),
        "started_at": _iso(_pick(status, "start_time", "startTime")),
        "age_seconds": _age_seconds(created),
        # Run state provides the original task identifier.
        # Kubernetes labels replace unsupported characters and cannot provide this identifier.
        "run_id": owner.get("run_id") or str(labels.get(f"{_EVAL_POD_LABEL}-run") or ""),
        "task_id": owner.get("task_id") or str(labels.get(f"{_EVAL_POD_LABEL}-task") or ""),
        "task_title": owner.get("task_title", ""),
        "task_phase": owner.get("task_phase") or str(labels.get(f"{_EVAL_POD_LABEL}-phase") or "agent"),
    }


def _shape_event(event: dict) -> dict:
    source = event.get("source") or {}
    series = event.get("series") or {}
    last = (
        _pick(event, "last_timestamp", "lastTimestamp")
        or _pick(series, "last_observed_time", "lastObservedTime")
        or _pick(event, "event_time", "eventTime")
    )
    return {
        "type": str(event.get("type") or "Normal"),
        "reason": str(event.get("reason") or ""),
        "message": redact(str(event.get("message") or "")),
        "count": int(event.get("count") or series.get("count") or 1),
        "first_seen": _iso(_pick(event, "first_timestamp", "firstTimestamp")),
        "last_seen": _iso(last),
        "age_seconds": _age_seconds(last),
        "source": str(_pick(source, "component", default="") or ""),
    }


# Docker.


class DockerSandboxView:
    """Local mode: the same panel over the host Docker daemon.

    Docker has no namespaces, so ownership is proven against run state: a
    container is this org's only if the run id in its labels names a run
    directory under this org's eval root.
    """

    backend = "docker"
    supports_live_logs = True

    def __init__(self, settings: EvalRunSettings, *, org_id: str) -> None:
        if not org_id:
            raise ValueError("org_id is required to read eval sandboxes")
        self._org_id = org_id
        transport = httpx.AsyncHTTPTransport(uds=settings.docker_socket)
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(15.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _owns(self, labels: dict) -> bool:
        run_id = str(labels.get(f"{_DOCKER_LABEL}.run") or "")
        return bool(run_id) and await runner.run_exists(self._org_id, run_id)

    async def _list_raw(self) -> list[dict]:
        resp = await self._client.get(
            f"{_DOCKER_API}/containers/json",
            params={"all": "1", "filters": json.dumps({"label": [f"{_DOCKER_LABEL}=1"]})},
        )
        resp.raise_for_status()
        return list(resp.json())

    async def inventory(self) -> dict:
        try:
            raw = await self._list_raw()
        except Exception as exc:
            logger.warning("Eval sandbox list failed on the Docker socket: %s", exc)
            return {
                "backend": self.backend,
                "live": False,
                "supports_live_logs": True,
                "namespace": "",
                "message": f"Could not reach the Docker daemon: {type(exc).__name__}",
                "sandboxes": [],
            }
        owners = await runner.sandbox_index(self._org_id)
        mine = [c for c in raw if await self._owns(c.get("Labels") or {})]
        return {
            "backend": self.backend,
            "live": True,
            "supports_live_logs": True,
            "namespace": "",
            "message": "",
            "sandboxes": [_shape_container(c, owners) for c in mine],
        }

    async def events(self, name: str) -> dict:
        return {
            "backend": self.backend,
            "supported": False,
            "message": "Scheduling events are a Kubernetes concept — local sandboxes have none.",
            "events": [],
        }

    async def _resolve_owned(self, name: str) -> str:
        """Full container id for `name` if this org owns it, else ""."""
        try:
            raw = await self._list_raw()
        except Exception:
            return ""
        for c in raw:
            cid = str(c.get("Id") or "")
            if cid.startswith(name) and await self._owns(c.get("Labels") or {}):
                return cid
        return ""

    async def stream_logs(self, name: str, *, tail_lines: int) -> AsyncIterator[tuple[str, str]]:
        cid = await self._resolve_owned(name)
        if not cid:
            yield "end", "not-found"
            return
        sent = 0
        redactor = _RedactionBuffer()
        deadline = asyncio.get_event_loop().time() + LOG_STREAM_MAX_SECONDS
        try:
            async with self._client.stream(
                "GET",
                f"{_DOCKER_API}/containers/{cid}/logs",
                params={"follow": "1", "stdout": "1", "stderr": "1", "tail": str(tail_lines)},
                timeout=httpx.Timeout(None, connect=15.0),
            ) as resp:
                if resp.status_code != 200:
                    yield "error", f"docker logs returned {resp.status_code}"
                    yield "end", "attach-failed"
                    return
                async for chunk in resp.aiter_bytes(4096):
                    sent += len(chunk)
                    if safe := redactor.feed(chunk.decode("utf-8", errors="replace")):
                        yield "log", safe
                    if sent >= LOG_STREAM_MAX_BYTES:
                        if safe := redactor.flush():
                            yield "log", safe
                        yield "end", "byte-cap"
                        return
                    if asyncio.get_event_loop().time() >= deadline:
                        if safe := redactor.flush():
                            yield "log", safe
                        yield "end", "deadline"
                        return
            if safe := redactor.flush():
                yield "log", safe
            yield "end", "sandbox-exited"
        except Exception as exc:
            yield "error", f"log stream ended: {type(exc).__name__}"
            yield "end", "stream-error"


_DOCKER_PHASE = {"created": "pending", "running": "running", "restarting": "pending", "paused": "running"}


def _shape_container(c: dict, owners: dict[str, dict]) -> dict:
    labels = c.get("Labels") or {}
    cid = str(c.get("Id") or "")
    state = str(c.get("State") or "").lower()
    owner = owners.get(cid, {}) or owners.get(cid[:12], {})
    return {
        "name": cid[:12],
        "backend": "docker",
        "phase": _DOCKER_PHASE.get(state, "succeeded" if state == "exited" else "unknown"),
        "reason": redact(str(c.get("Status") or state or "")),
        "message": "",
        "ready": state == "running",
        "oom_killed": "OOMKilled" in str(c.get("Status") or ""),
        "restart_count": 0,
        "node": "local",
        "created_at": _iso(datetime.fromtimestamp(float(c.get("Created") or 0), UTC)) if c.get("Created") else "",
        "started_at": "",
        "age_seconds": _age_seconds(c.get("Created")),
        "run_id": owner.get("run_id") or str(labels.get(f"{_DOCKER_LABEL}.run") or ""),
        "task_id": owner.get("task_id") or str(labels.get(f"{_DOCKER_LABEL}.task") or ""),
        "task_title": owner.get("task_title", ""),
        "task_phase": owner.get("task_phase") or str(labels.get(f"{_DOCKER_LABEL}.phase") or "agent"),
    }


# Selection.


def get_sandbox_view(org_id: str) -> SandboxView:
    """Pick the introspection view for the current deployment mode.

    Mirrors `get_execution_backend` so the panel always reads the same runtime
    the runner writes to: cloud never falls back to the Docker socket.
    """
    from ..runtime.mode import is_cloud_mode

    settings = get_eval_run_settings()
    if is_cloud_mode():
        return KubernetesSandboxView(settings, org_id=org_id)
    return DockerSandboxView(settings, org_id=org_id)
