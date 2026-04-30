"""Local API key management (file-based, local mode only)."""

from __future__ import annotations

import logging
import secrets

import gateway.store._atomic as _atomic
import gateway.store._constants as _constants
from gateway.deployment import is_cloud_mode

logger = logging.getLogger(__name__)


def get_local_api_key() -> str | None:
    if is_cloud_mode():
        return None
    _constants.DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file = _constants.DATA_DIR / "local_api_key"
    new_key = "sp_local_" + secrets.token_hex(16)
    result = _atomic._atomic_create_file(key_file, new_key.encode()).decode().strip()
    if result:
        return result
    # File existed but was empty (should not occur with O_EXCL writes, but guard anyway).
    key_file.unlink(missing_ok=True)
    new_key2 = "sp_local_" + secrets.token_hex(16)
    logger.info("Generated new local API key (stored in %s)", key_file)
    return _atomic._atomic_create_file(key_file, new_key2.encode()).decode().strip()
