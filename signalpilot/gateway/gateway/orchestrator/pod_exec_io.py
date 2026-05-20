"""Pod exec I/O — SOLE authorized caller of kubernetes pods/exec.

This module is the ONLY file that may import or call:
    kubernetes_asyncio.stream.WsApiClient
    connect_get_namespaced_pod_exec
    kubernetes_asyncio.stream

All other gateway code that needs to transfer files to/from a pod must go
through stream_tar_into_pod / stream_tar_out_of_pod — never by calling the
K8s exec API directly. This is enforced by an AST test (C4):
    tests/test_pod_exec_caller_invariant.py

Design constraints (C4):
    - Public functions have NO 'command' parameter (command is hardcoded internally).
    - Container name is hardcoded to "notebook".
    - dest_path / src_path MUST start with "/workspace/" (validated; ValueError otherwise).
    - Command list is a Python list literal containing only "tar" — no sh -c, no
      string interpolation into argv.
    - Tar exit code MUST be 0; non-zero raises RuntimeError (no silent skip).

Sentinel ordering (C1):
    stream_tar_into_pod accepts an optional sentinel_last parameter. When provided,
    that file is added as the LAST member of the tar archive regardless of its
    lexicographic position. This guarantees the pod's sentinel-wait shim only exits
    after ALL workspace content is extracted.

Security (V1–V3):
    - stream_tar_out_of_pod uses filter="data" on extractall (Python 3.12) to reject
      path traversal, absolute paths, symlinks pointing outside dest_dir, and device files.
    - stream_tar_into_pod skips symlinks and validates arcnames (no leading /, no ..).
    - Both functions skip symlinks from the source tree.

kubernetes_asyncio 32.x exec API (S9):
    ws_api = WsApiClient(aiohttp_client_session=session)  # wraps core_api.api_client
    ws = await ws_api.connect_get_namespaced_pod_exec(
        name=pod_name, namespace=namespace, container="notebook",
        command=[...], stderr=True, stdin=True, stdout=True, tty=False
    )
    The returned object exposes write_stdin(bytes), read_stdout(), read_stderr(),
    read_channel(n), returncode. Used as async context manager.
"""

from __future__ import annotations

import io
import logging
import os
import posixpath
import tarfile
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

_CONTAINER_NAME = "notebook"
_WORKSPACE_PREFIX = "/workspace/"


def _validate_workspace_path(path: str, label: str) -> None:
    """Ensure path starts with /workspace/ and contains no traversal. Raises ValueError."""
    if not path.startswith(_WORKSPACE_PREFIX):
        raise ValueError(
            f"{label} must start with '/workspace/'. Got: {path!r}"
        )
    if ".." in PurePosixPath(path).parts:
        raise ValueError(
            f"{label} must not contain '..'. Got: {path!r}"
        )
    if posixpath.normpath(path) != path.rstrip("/"):
        raise ValueError(
            f"{label} is not a normalized path. Got: {path!r}"
        )


def _validate_arcname(arcname: str) -> None:
    """Reject arcnames with leading '/', '..', or NUL. Raises ValueError."""
    if arcname.startswith("/"):
        raise ValueError(f"Tar arcname must not start with '/': {arcname!r}")
    parts = Path(arcname).parts
    if ".." in parts:
        raise ValueError(f"Tar arcname must not contain '..': {arcname!r}")
    if "\x00" in arcname:
        raise ValueError(f"Tar arcname must not contain NUL: {arcname!r}")


async def stream_tar_into_pod(
    core_api,
    *,
    namespace: str,
    pod_name: str,
    src_dir: Path,
    dest_path: str,
    sentinel_last: Path | None = None,
) -> None:
    """Stream a tar archive of src_dir into dest_path inside the pod.

    The pod receives a tar stream on stdin and extracts it with:
        tar -xf - -C <dest_path>

    dest_path MUST start with '/workspace/'. Raises ValueError otherwise.
    Raises RuntimeError if tar exits non-zero.

    sentinel_last: if provided, this file (which must be inside src_dir) is added
    as the LAST member of the tar archive regardless of its lexicographic position.
    Use this to ensure the workspace sentinel is written after all content files (C1).

    Symlinks are skipped (V3). arcnames are validated for traversal (V3).
    """
    _validate_workspace_path(dest_path, "dest_path")

    sentinel_rel: str | None = None
    if sentinel_last is not None:
        sentinel_rel = str(sentinel_last.relative_to(src_dir))

    # Build tar in memory from src_dir.
    # Non-sentinel files first (sorted), sentinel (if any) explicitly last.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for file_path in sorted(src_dir.rglob("*")):
            if file_path.is_symlink():
                logger.warning("Skipping symlink in workspace tar-in: %s", file_path)
                continue
            if not file_path.is_file():
                continue
            arcname = str(file_path.relative_to(src_dir))
            if sentinel_rel is not None and arcname == sentinel_rel:
                # Skip here; will be added last below.
                continue
            _validate_arcname(arcname)
            tf.add(file_path, arcname=arcname)

        # Add sentinel as the absolute last member.
        if sentinel_last is not None and sentinel_last.exists() and sentinel_rel is not None:
            _validate_arcname(sentinel_rel)
            tf.add(sentinel_last, arcname=sentinel_rel)

    tar_bytes = buf.getvalue()

    command = ["tar", "-xf", "-", "-C", dest_path]
    await _exec_with_stdin(
        core_api,
        namespace=namespace,
        pod_name=pod_name,
        command=command,
        stdin_data=tar_bytes,
        label="tar-into-pod",
    )


async def stream_tar_out_of_pod(
    core_api,
    *,
    namespace: str,
    pod_name: str,
    src_path: str,
    dest_dir: Path,
) -> None:
    """Stream a tar archive of src_path out of the pod into dest_dir.

    The pod produces a tar stream on stdout using:
        tar -cf - -C <src_path> .

    src_path MUST start with '/workspace/'. Raises ValueError otherwise.
    Raises RuntimeError if tar exits non-zero.
    """
    _validate_workspace_path(src_path, "src_path")

    command = ["tar", "-cf", "-", "-C", src_path, "."]
    tar_bytes = await _exec_with_stdout(
        core_api,
        namespace=namespace,
        pod_name=pod_name,
        command=command,
        label="tar-out-of-pod",
    )

    # Extract into dest_dir.
    # filter="data" rejects path traversal, absolute paths, symlinks pointing
    # outside dest_dir, and device/FIFO files (Python 3.12 stdlib; V1 fix).
    dest_dir.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO(tar_bytes)
    with tarfile.open(fileobj=buf, mode="r") as tf:
        tf.extractall(path=dest_dir, filter="data")


async def _exec_with_stdin(
    core_api,
    *,
    namespace: str,
    pod_name: str,
    command: list[str],
    stdin_data: bytes,
    label: str,
) -> None:
    """Execute command in pod, sending stdin_data on stdin. Raises on non-zero exit."""
    import json as _json

    from kubernetes_asyncio import client
    from kubernetes_asyncio.stream import WsApiClient

    cfg = core_api.api_client.configuration
    async with WsApiClient(configuration=cfg) as ws_client:
        v1 = client.CoreV1Api(api_client=ws_client)
        ws_connect = await v1.connect_get_namespaced_pod_exec(
            name=pod_name,
            namespace=namespace,
            container=_CONTAINER_NAME,
            command=command,
            stderr=True,
            stdin=True,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        async with ws_connect as ws:
            stdin_channel = b"\x00"
            chunk_size = 64 * 1024
            for offset in range(0, len(stdin_data), chunk_size):
                chunk = stdin_data[offset : offset + chunk_size]
                await ws.send_bytes(stdin_channel + chunk)
            await ws.send_bytes(b"\x00")

            stdout_buf = bytearray()
            stderr_buf = bytearray()
            rc = None
            async for msg in ws:
                data = msg.data
                if isinstance(data, str):
                    data = data.encode("utf-8")
                if len(data) < 1:
                    continue
                channel = data[0]
                payload = data[1:]
                if channel == 1:
                    stdout_buf.extend(payload)
                elif channel == 2:
                    stderr_buf.extend(payload)
                elif channel == 3:
                    try:
                        status = _json.loads(payload.decode("utf-8"))
                        rc = 0 if status.get("status") == "Success" else int(
                            status["details"]["causes"][0]["message"]
                        )
                    except Exception:
                        rc = 1

    if rc is None:
        rc = 0
    if rc != 0:
        raise RuntimeError(
            f"{label} tar failed: rc={rc}, stderr={bytes(stderr_buf)!r}"
        )
    logger.debug("%s complete: %d bytes sent", label, len(stdin_data))


async def _exec_with_stdout(
    core_api,
    *,
    namespace: str,
    pod_name: str,
    command: list[str],
    label: str,
) -> bytes:
    """Execute command in pod, capturing stdout. Raises on non-zero exit."""
    import json as _json

    from kubernetes_asyncio import client
    from kubernetes_asyncio.stream import WsApiClient

    cfg = core_api.api_client.configuration
    async with WsApiClient(configuration=cfg) as ws_client:
        v1 = client.CoreV1Api(api_client=ws_client)
        ws_connect = await v1.connect_get_namespaced_pod_exec(
            name=pod_name,
            namespace=namespace,
            container=_CONTAINER_NAME,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        async with ws_connect as ws:
            stdout_buf = bytearray()
            stderr_buf = bytearray()
            rc = None
            async for msg in ws:
                data = msg.data
                if isinstance(data, str):
                    data = data.encode("utf-8")
                if len(data) < 1:
                    continue
                channel = data[0]
                payload = data[1:]
                if channel == 1:
                    stdout_buf.extend(payload)
                elif channel == 2:
                    stderr_buf.extend(payload)
                elif channel == 3:
                    try:
                        status = _json.loads(payload.decode("utf-8"))
                        rc = 0 if status.get("status") == "Success" else int(
                            status["details"]["causes"][0]["message"]
                        )
                    except Exception:
                        rc = 1

    if rc is None:
        rc = 0
    if rc != 0:
        raise RuntimeError(
            f"{label} tar failed: rc={rc}, stderr={bytes(stderr_buf)!r}"
        )
    logger.debug("%s complete: %d bytes received", label, len(stdout) if stdout else 0)
    return stdout if stdout else b""
