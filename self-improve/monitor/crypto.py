"""Fernet encryption for credential storage.

Uses AES-128-CBC with HMAC-SHA256 via the cryptography library's Fernet
implementation. The master key is auto-generated on first boot and stored
in a file on the shared Docker volume.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet


_fernet: Fernet | None = None


def _get_fernet(key_path: str) -> Fernet:
    """Get or create the Fernet instance, generating a key if needed."""
    global _fernet
    if _fernet is not None:
        return _fernet

    p = Path(key_path)
    if p.exists():
        key = p.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(key)
        try:
            os.chmod(str(p), 0o600)
        except OSError:
            pass  # Best-effort on Windows / Docker

    _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str, key_path: str) -> str:
    """Encrypt a plaintext string. Returns a Fernet token as a UTF-8 string."""
    f = _get_fernet(key_path)
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str, key_path: str) -> str:
    """Decrypt a Fernet token back to plaintext."""
    f = _get_fernet(key_path)
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def mask(value: str, prefix_len: int = 4) -> str:
    """Mask a secret value, showing only the first *prefix_len* characters."""
    if len(value) <= prefix_len:
        return "****"
    return value[:prefix_len] + "*" * (len(value) - prefix_len)
