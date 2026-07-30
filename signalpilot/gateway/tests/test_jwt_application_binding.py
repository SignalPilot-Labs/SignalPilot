"""Cloud mode must bind Clerk JWTs to this application.

Without CLERK_JWT_AUDIENCE or SP_EXPECTED_AZP, any token the Clerk instance
issues is accepted — including one minted for a different application on the
same instance. The gateway refuses to boot in that state.

The module runs its startup checks at import time, so each case re-imports it
under a patched environment.
"""

from __future__ import annotations

import importlib
import sys

import pytest

MODULE = "gateway.auth.user"


def _reimport(monkeypatch, **env):
    """Re-import gateway.auth.user with the given environment."""
    for key in (
        "SP_DEPLOYMENT_MODE",
        "CLERK_PUBLISHABLE_KEY",
        "CLERK_JWT_AUDIENCE",
        "SP_EXPECTED_AZP",
        "SP_ALLOW_UNBOUND_JWT_AUDIENCE",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    # Config objects are cached, so drop them too.
    for name in ("gateway.config.auth", "gateway.config"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "get_auth_settings"):
            getattr(mod, "get_auth_settings").cache_clear()
    return importlib.import_module(MODULE)


# A publishable key whose decoded domain is a host we never contact during import
# of the guard under test. Format: pk_test_<base64("host$")>.
_PK = "pk_test_ZXhhbXBsZS5jbGVyay5hY2NvdW50cy5kZXYk"


class TestCloudRequiresApplicationBinding:
    def test_boot_fails_when_neither_audience_nor_azp_is_set(self, monkeypatch):
        with pytest.raises(RuntimeError) as exc:
            _reimport(monkeypatch, SP_DEPLOYMENT_MODE="cloud", CLERK_PUBLISHABLE_KEY=_PK)
        message = str(exc.value)
        assert "CLERK_JWT_AUDIENCE" in message
        assert "SP_EXPECTED_AZP" in message
        # The message must warn that setting the variable alone is not enough,
        # because Clerk's default session token carries neither claim.
        assert "401" in message

    def test_audience_alone_satisfies_the_requirement(self, monkeypatch):
        mod = _reimport(
            monkeypatch,
            SP_DEPLOYMENT_MODE="cloud",
            CLERK_PUBLISHABLE_KEY=_PK,
            CLERK_JWT_AUDIENCE="signalpilot",
        )
        assert mod.EXPECTED_AUDIENCE == "signalpilot"

    def test_azp_alone_satisfies_the_requirement(self, monkeypatch):
        mod = _reimport(
            monkeypatch,
            SP_DEPLOYMENT_MODE="cloud",
            CLERK_PUBLISHABLE_KEY=_PK,
            SP_EXPECTED_AZP="https://app.signalpilot.ai",
        )
        assert "https://app.signalpilot.ai" in mod.EXPECTED_AZP

    def test_explicit_override_boots_but_is_deliberate(self, monkeypatch):
        mod = _reimport(
            monkeypatch,
            SP_DEPLOYMENT_MODE="cloud",
            CLERK_PUBLISHABLE_KEY=_PK,
            SP_ALLOW_UNBOUND_JWT_AUDIENCE="1",
        )
        assert mod.EXPECTED_AUDIENCE == ""
        assert not mod.EXPECTED_AZP

    def test_local_mode_is_unaffected(self, monkeypatch):
        mod = _reimport(monkeypatch, SP_DEPLOYMENT_MODE="local")
        assert mod is not None
