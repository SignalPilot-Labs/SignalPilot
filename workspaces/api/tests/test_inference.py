"""Tests for resolve_inference_source."""

from __future__ import annotations

import pytest

from workspaces_api.agent.inference import InferenceBundle, resolve_inference_source
from workspaces_api.config import Settings
from workspaces_api.errors import InferenceNotConfigured, MeteredNotImplemented


class TestInference:
    def test_local_with_token_returns_bundle(
        self, settings_local: Settings
    ) -> None:
        bundle = resolve_inference_source(settings_local, requested=None)
        assert bundle.mode == "local"
        assert bundle.oauth_token == "test-token"
        assert bundle.api_key is None

    def test_local_explicit_request_returns_bundle(
        self, settings_local: Settings
    ) -> None:
        bundle = resolve_inference_source(settings_local, requested="local")
        assert bundle.mode == "local"

    def test_local_without_token_raises(self) -> None:
        s = Settings.model_validate({
            "SP_DEPLOYMENT_MODE": "local",
            "WORKSPACES_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        })
        with pytest.raises(InferenceNotConfigured):
            resolve_inference_source(s, requested=None)

    def test_local_unsupported_requested_raises(
        self, settings_local: Settings
    ) -> None:
        with pytest.raises(InferenceNotConfigured):
            resolve_inference_source(settings_local, requested="byo")

    def test_cloud_byo_with_key_returns_bundle(
        self, settings_cloud_byo: Settings
    ) -> None:
        bundle = resolve_inference_source(settings_cloud_byo, requested=None)
        assert bundle.mode == "byo"
        assert bundle.api_key == "sk-ant-test-key"
        assert bundle.oauth_token is None

    def test_cloud_byo_explicit_request(self, settings_cloud_byo: Settings) -> None:
        bundle = resolve_inference_source(settings_cloud_byo, requested="byo")
        assert bundle.mode == "byo"

    def test_cloud_byo_without_key_raises(self, settings_cloud_no_key: Settings) -> None:
        with pytest.raises(InferenceNotConfigured):
            resolve_inference_source(settings_cloud_no_key, requested=None)

    def test_cloud_metered_raises_metered_not_implemented(
        self, settings_cloud_byo: Settings
    ) -> None:
        with pytest.raises(MeteredNotImplemented):
            resolve_inference_source(settings_cloud_byo, requested="metered")

    def test_repr_does_not_contain_oauth_token(self) -> None:
        bundle = InferenceBundle(
            mode="local",
            oauth_token="my-secret-oauth-token",
            api_key=None,
            base_url=None,
        )
        rep = repr(bundle)
        assert "my-secret-oauth-token" not in rep
        assert "***" in rep

    def test_repr_does_not_contain_api_key(self) -> None:
        bundle = InferenceBundle(
            mode="byo",
            oauth_token=None,
            api_key="sk-ant-super-secret-key",
            base_url=None,
        )
        rep = repr(bundle)
        assert "sk-ant-super-secret-key" not in rep
        assert "***" in rep

    def test_repr_shows_none_for_absent_secrets(self) -> None:
        bundle = InferenceBundle(
            mode="local",
            oauth_token=None,
            api_key=None,
            base_url=None,
        )
        rep = repr(bundle)
        assert "None" in rep
