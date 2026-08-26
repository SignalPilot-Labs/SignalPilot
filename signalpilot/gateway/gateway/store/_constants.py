"""Constants for the gateway store package."""

from __future__ import annotations

import os
from pathlib import Path

# Class B: SP_DATA_DIR stays as os.getenv: tests/test_governance_scoping.py mutates
# SP_DATA_DIR after import and expects governance/annotations.py:151 to pick it up per-call.
# Do NOT migrate DATA_DIR to a cached settings object.
DATA_DIR = Path(os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot")))

PBKDF2_ITERATIONS = 600_000
PBKDF2_KEY_LENGTH = 32
SALT_FILE_NAME = ".encryption_salt"
KEY_FILE_NAME = ".encryption_key"

OLD_ENCRYPTION_KEY_ENV = "SP_ENCRYPTION_KEY_OLD"

# This value identifies the active encryption key material.
# Increase it during key rotation and set the new key in SP_ENCRYPTION_KEY.
# SP_ENCRYPTION_KEY_OLD provides the secondary decryption key during rotation.
CURRENT_KEY_VERSION = 1
