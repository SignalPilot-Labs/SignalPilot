"""Tests for the monitor crypto module (Fernet encryption)."""

import os
import tempfile
import pytest

from monitor import crypto


@pytest.fixture
def key_path(tmp_path):
    """Provide a temporary key path and reset the cached Fernet instance."""
    crypto._fernet = None
    path = str(tmp_path / "test.key")
    yield path
    crypto._fernet = None


class TestEncryptDecrypt:
    def test_roundtrip(self, key_path):
        plaintext = "my-secret-api-key-12345"
        encrypted = crypto.encrypt(plaintext, key_path)
        assert encrypted != plaintext
        decrypted = crypto.decrypt(encrypted, key_path)
        assert decrypted == plaintext

    def test_key_file_created(self, key_path):
        crypto.encrypt("test", key_path)
        assert os.path.exists(key_path)

    def test_key_reused_across_calls(self, key_path):
        enc1 = crypto.encrypt("test", key_path)
        crypto._fernet = None  # Force reload from file
        dec = crypto.decrypt(enc1, key_path)
        assert dec == "test"

    def test_empty_string(self, key_path):
        encrypted = crypto.encrypt("", key_path)
        decrypted = crypto.decrypt(encrypted, key_path)
        assert decrypted == ""

    def test_unicode(self, key_path):
        plaintext = "秘密のキー 🔑"
        encrypted = crypto.encrypt(plaintext, key_path)
        decrypted = crypto.decrypt(encrypted, key_path)
        assert decrypted == plaintext

    def test_wrong_key_fails(self, tmp_path):
        crypto._fernet = None
        key1 = str(tmp_path / "key1")
        key2 = str(tmp_path / "key2")

        encrypted = crypto.encrypt("secret", key1)
        crypto._fernet = None  # Reset so it loads key2
        with pytest.raises(Exception):  # InvalidToken
            crypto.decrypt(encrypted, key2)


class TestMask:
    def test_masks_long_value(self):
        value = "sk-abc123456789"
        result = crypto.mask(value)
        assert result[:4] == "sk-a"
        assert result[4:] == "*" * (len(value) - 4)

    def test_masks_short_value(self):
        assert crypto.mask("abc") == "****"

    def test_masks_exact_prefix_len(self):
        assert crypto.mask("abcd") == "****"

    def test_custom_prefix_len(self):
        result = crypto.mask("ghp_abcdef123456", prefix_len=8)
        assert result.startswith("ghp_abcd")
        assert result.endswith("********")
