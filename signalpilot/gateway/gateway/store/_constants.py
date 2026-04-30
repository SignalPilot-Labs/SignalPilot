"""Constants for the gateway store package."""

from __future__ import annotations

import os
from pathlib import Path

from ..config import get_storage_settings

# Class B: SP_DATA_DIR stays as os.getenv — tests/test_governance_scoping.py mutates
# SP_DATA_DIR after import and expects governance/annotations.py:151 to pick it up per-call.
# Do NOT migrate DATA_DIR to a cached settings object.
DATA_DIR = Path(os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot")))

# Legacy bare SHA-256 derivation is disabled by default. Existing deployments
# that still have rows encrypted with the old key can temporarily set
# SP_ALLOW_LEGACY_CRYPTO=true while migrating, then disable it again.
# SP_ALLOW_LEGACY_CRYPTO semantics: only "true" (any case) is truthy — see config/storage.py.
_ALLOW_LEGACY_CRYPTO = get_storage_settings().allow_legacy_crypto

PBKDF2_ITERATIONS = 600_000
PBKDF2_KEY_LENGTH = 32
SALT_FILE_NAME = ".encryption_salt"
KEY_FILE_NAME = ".encryption_key"

# Key version tracking for rotation support.
# Bump this constant when rotating to a new key material. When bumped, the operator
# sets the new key via SP_ENCRYPTION_KEY and the old key is kept for decryption
# of legacy rows (future multi-key read logic). Currently only version 1 exists.
# key_version is orthogonal to _decrypt_with_migration: that handles "which derivation
# method" while key_version handles "which key material".
CURRENT_KEY_VERSION = 1
