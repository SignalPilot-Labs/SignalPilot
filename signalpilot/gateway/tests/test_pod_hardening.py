"""Tests for F-7a/b pod hardening: readOnlyRootFilesystem, emptyDir sizeLimit,
ephemeral-storage requests/limits, and main container argv-only invariant."""
from __future__ import annotations

import pytest


def _make_manifest(**kwargs):
    from gateway.orchestrator.kubernetes import _pod_manifest

    defaults = dict(
        pod_name="nb-hard",
        namespace="default",
        image="signalpilot-notebook:latest",
        user_id="user-1",
        org_id="org-1",
        project_id=None,
        branch="main",
        gateway_url="http://localhost:3300",
        session_jwt_secret_name="sp-jwt-nb-hard",
        session_id="sess-hard",
        access_token=None,
    )
    defaults.update(kwargs)
    return _pod_manifest(**defaults)


class TestReadOnlyRootFilesystem:
    def test_main_container_readonly_root(self):
        """Main container has readOnlyRootFilesystem: True (F-7a)."""
        manifest = _make_manifest()
        ctx = manifest["spec"]["containers"][0]["securityContext"]
        assert ctx.get("readOnlyRootFilesystem") is True

    def test_init_container_readonly_root(self):
        """jwt-stager initContainer has readOnlyRootFilesystem: True (F-7a)."""
        manifest = _make_manifest()
        init = manifest["spec"]["initContainers"][0]
        ctx = init["securityContext"]
        assert ctx.get("readOnlyRootFilesystem") is True


class TestEmptyDirSizeLimits:
    def test_all_emptydir_volumes_have_size_limit(self):
        """Every emptyDir volume has a sizeLimit set (F-7b)."""
        manifest = _make_manifest()
        volumes = manifest["spec"]["volumes"]
        for vol in volumes:
            if "emptyDir" in vol:
                assert "sizeLimit" in vol["emptyDir"], (
                    f"emptyDir volume {vol['name']!r} is missing sizeLimit"
                )

    def test_session_jwt_emptydir_uses_memory_medium(self):
        """session-jwt emptyDir uses medium: Memory."""
        manifest = _make_manifest()
        volumes = {v["name"]: v for v in manifest["spec"]["volumes"]}
        jwt_vol = volumes["session-jwt"]
        assert jwt_vol["emptyDir"].get("medium") == "Memory"


class TestEphemeralStorage:
    def test_main_container_ephemeral_storage_requests(self):
        """Main container has ephemeral-storage in resource requests (F-7b)."""
        manifest = _make_manifest()
        resources = manifest["spec"]["containers"][0]["resources"]
        assert "ephemeral-storage" in resources["requests"]

    def test_main_container_ephemeral_storage_limits(self):
        """Main container has ephemeral-storage in resource limits (F-7b)."""
        manifest = _make_manifest()
        resources = manifest["spec"]["containers"][0]["resources"]
        assert "ephemeral-storage" in resources["limits"]


class TestArgvOnlyMainContainer:
    def test_main_container_command_no_sh(self):
        """Main container command contains no 'sh' element (F-4 argv-only invariant)."""
        manifest = _make_manifest()
        command = manifest["spec"]["containers"][0]["command"]
        assert "sh" not in command, (
            f"Main container command must not contain 'sh': {command}"
        )

    def test_init_container_sh_has_no_interpolation_markers(self):
        """initContainer sh -c is allowed but must have no variable interpolation."""
        manifest = _make_manifest()
        init = manifest["spec"]["initContainers"][0]
        # initContainer is explicitly allowed to use sh -c (constant text only).
        cmd = init["command"]
        assert cmd[0] == "sh"
        cmd_str = cmd[2]
        assert "$" not in cmd_str, f"initContainer sh -c must not contain '$': {cmd_str}"
        assert "`" not in cmd_str, f"initContainer sh -c must not contain backticks: {cmd_str}"
