"""Prepare the local API key file for Docker development.

This module intentionally avoids importing gateway.store. The store package
pulls in database-backed modules at import time, which can block gateway
startup before Uvicorn has a chance to serve health checks.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from gateway.runtime.mode import is_cloud_mode


def _atomic_create_file(path: Path, content: bytes, mode: int = 0o600) -> bytes:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
        return content
    except FileExistsError:
        return path.read_bytes()


def _write_shared_key(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(key, encoding="utf-8")
    os.replace(tmp_path, path)


def get_or_create_local_api_key() -> str | None:
    if is_cloud_mode():
        return None

    data_dir = Path(os.environ.get("SP_DATA_DIR", str(Path.home() / ".signalpilot")))
    data_dir.mkdir(parents=True, exist_ok=True)

    key_file = data_dir / "local_api_key"
    new_key = "sp_local_" + secrets.token_hex(16)
    key = _atomic_create_file(key_file, new_key.encode()).decode().strip()
    if key:
        return key

    key_file.unlink(missing_ok=True)
    new_key = "sp_local_" + secrets.token_hex(16)
    return _atomic_create_file(key_file, new_key.encode()).decode().strip()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    shared_path = Path(args[0]) if args else None

    key = get_or_create_local_api_key()
    if key and shared_path is not None:
        _write_shared_key(shared_path, key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
