"""Tests for F-3: K8s config validator rejects CIDRs containing AWS IMDS."""

from __future__ import annotations

import pytest


def _make_settings(egress_cidr: str | None):
    """Instantiate K8sSettings with only SP_NOTEBOOK_EGRESS_CIDR overridden."""
    from pydantic import ValidationError

    from gateway.config.k8s import K8sSettings

    env = {
        "SP_DEPLOYMENT_MODE": "local",
        "SP_NOTEBOOK_UPSTREAM_MODE": "local",
    }
    if egress_cidr is not None:
        env["SP_NOTEBOOK_EGRESS_CIDR"] = egress_cidr
    return K8sSettings.model_validate(env)


class TestEgressCidrValidation:
    def test_egress_cidr_rejects_imds_v4(self):
        """0.0.0.0/0 contains 169.254.169.254 — validator must reject it."""
        from pydantic import ValidationError

        with pytest.raises((ValueError, ValidationError), match="IMDS"):
            _make_settings("0.0.0.0/0")

    def test_egress_cidr_rejects_link_local_only(self):
        """169.254.0.0/16 itself contains the IMDS address — must be rejected."""
        from pydantic import ValidationError

        with pytest.raises((ValueError, ValidationError), match="IMDS"):
            _make_settings("169.254.0.0/16")

    def test_egress_cidr_rejects_imds_v6(self):
        """fd00:ec2::/32 (exact IMDS v6 range) must be rejected."""
        from pydantic import ValidationError

        with pytest.raises((ValueError, ValidationError), match="IMDS"):
            _make_settings("fd00:ec2::/32")

    def test_egress_cidr_rejects_imds_v6_supernet(self):
        """::/0 overlaps fd00:ec2::/32 — must be rejected."""
        from pydantic import ValidationError

        with pytest.raises((ValueError, ValidationError), match="IMDS"):
            _make_settings("::/0")

    def test_egress_cidr_accepts_safe_range(self):
        """52.0.0.0/8 does not contain IMDS — must be accepted."""
        settings = _make_settings("52.0.0.0/8")
        assert settings.sp_notebook_egress_cidr == "52.0.0.0/8"

    def test_egress_cidr_none_accepted(self):
        """None (unset) must be accepted — no validation needed."""
        settings = _make_settings(None)
        assert settings.sp_notebook_egress_cidr is None
