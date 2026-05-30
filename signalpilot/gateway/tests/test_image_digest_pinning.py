"""Tests for F-18: SP_NOTEBOOK_IMAGE digest pinning in cloud mode.

Cases:
  1. Cloud mode + plain tag → ValidationError.
  2. Cloud mode + valid @sha256:<64-hex> → loads.
  3. Cloud mode + 63-hex digest → rejected.
  4. Local mode + plain tag → loads.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError


def _make_k8s_settings(env_overrides: dict[str, str]) -> object:
    """Create K8sSettings with a clean lru_cache, using env_overrides."""
    import gateway.config.k8s as k8s_mod

    k8s_mod.get_k8s_settings.cache_clear()
    try:
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env_overrides.items():
                mp.setenv(k, v)
            # Remove keys not in env_overrides but that might interfere
            from gateway.config.k8s import K8sSettings
            return K8sSettings()
    finally:
        k8s_mod.get_k8s_settings.cache_clear()


_VALID_DIGEST = "a" * 64
_VALID_IMAGE = f"your-registry/notebook@sha256:{_VALID_DIGEST}"

_CLOUD_REQUIRED_ENV = {
    "SP_DEPLOYMENT_MODE": "cloud",
    "SP_NOTEBOOK_RUNTIME_CLASS": "gvisor",
    "SP_PUBLIC_GATEWAY_URL": "https://gateway.example.com",
}


class TestImageDigestPinningCloudMode:
    """F-18: Cloud-mode digest enforcement."""

    def test_cloud_plain_tag_rejected(self):
        """Case 1: Cloud mode + plain tag → ValidationError."""
        env = {**_CLOUD_REQUIRED_ENV, "SP_NOTEBOOK_IMAGE": "signalpilot-notebook:latest"}
        with pytest.raises(ValidationError) as exc_info:
            _make_k8s_settings(env)
        assert "digest" in str(exc_info.value).lower() or "sha256" in str(exc_info.value).lower()

    def test_cloud_valid_digest_accepted(self):
        """Case 2: Cloud mode + valid @sha256:<64-hex> → loads."""
        env = {**_CLOUD_REQUIRED_ENV, "SP_NOTEBOOK_IMAGE": _VALID_IMAGE}
        settings = _make_k8s_settings(env)
        assert settings.sp_notebook_image == _VALID_IMAGE

    def test_cloud_63_hex_digest_rejected(self):
        """Case 3: Cloud mode + 63-hex digest → rejected (must be exactly 64 hex)."""
        short_digest = "b" * 63
        env = {**_CLOUD_REQUIRED_ENV, "SP_NOTEBOOK_IMAGE": f"registry/notebook@sha256:{short_digest}"}
        with pytest.raises(ValidationError):
            _make_k8s_settings(env)

    def test_cloud_no_digest_separator_rejected(self):
        """Extra: image with @sha256: but wrong format → rejected."""
        env = {**_CLOUD_REQUIRED_ENV, "SP_NOTEBOOK_IMAGE": "registry/notebook:v1.2.3"}
        with pytest.raises(ValidationError):
            _make_k8s_settings(env)

    def test_cloud_uppercase_hex_rejected(self):
        """Extra: uppercase hex is not accepted (must be lowercase)."""
        upper_digest = "A" * 64
        env = {**_CLOUD_REQUIRED_ENV, "SP_NOTEBOOK_IMAGE": f"registry/notebook@sha256:{upper_digest}"}
        with pytest.raises(ValidationError):
            _make_k8s_settings(env)


class TestImageDigestPinningLocalMode:
    """F-18: Local mode backcompat — floating tags allowed."""

    def test_local_plain_tag_accepted(self):
        """Case 4: Local mode + plain tag → loads (backcompat)."""
        env = {"SP_DEPLOYMENT_MODE": "local", "SP_NOTEBOOK_IMAGE": "signalpilot-notebook:latest"}
        settings = _make_k8s_settings(env)
        assert settings.sp_notebook_image == "signalpilot-notebook:latest"

    def test_local_no_mode_plain_tag_accepted(self):
        """Local mode (no SP_DEPLOYMENT_MODE) + plain tag → loads."""
        env = {"SP_NOTEBOOK_IMAGE": "signalpilot-notebook:dev"}
        # Ensure SP_DEPLOYMENT_MODE is not set
        import gateway.config.k8s as k8s_mod
        k8s_mod.get_k8s_settings.cache_clear()
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.delenv("SP_DEPLOYMENT_MODE", raising=False)
                mp.setenv("SP_NOTEBOOK_IMAGE", "signalpilot-notebook:dev")
                from gateway.config.k8s import K8sSettings
                settings = K8sSettings()
            assert settings.sp_notebook_image == "signalpilot-notebook:dev"
        finally:
            k8s_mod.get_k8s_settings.cache_clear()
