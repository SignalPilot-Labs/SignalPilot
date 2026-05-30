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


class TestInitContainerNonRoot:
    """F-14: initContainer runs as uid/gid 10001, no added capabilities, seccompProfile set."""

    def test_init_container_runs_as_non_root(self):
        """initContainer runAsUser==10001, runAsGroup==10001, runAsNonRoot==True (F-14)."""
        manifest = _make_manifest()
        init = manifest["spec"]["initContainers"][0]
        sc = init["securityContext"]
        assert sc["runAsUser"] == 10001
        assert sc["runAsGroup"] == 10001
        assert sc["runAsNonRoot"] is True

    def test_init_container_has_no_capabilities_added(self):
        """initContainer capabilities must have no 'add' list (F-14 gate test)."""
        manifest = _make_manifest()
        init = manifest["spec"]["initContainers"][0]
        caps = init["securityContext"]["capabilities"]
        assert caps.get("add", []) == [], (
            f"initContainer must not add any capabilities; got: {caps.get('add')}"
        )
        assert "ALL" in caps["drop"]

    def test_init_container_seccomp_runtime_default(self):
        """initContainer seccompProfile.type == 'RuntimeDefault' (F-14 PSS-restricted)."""
        manifest = _make_manifest()
        init = manifest["spec"]["initContainers"][0]
        seccomp = init["securityContext"].get("seccompProfile", {})
        assert seccomp.get("type") == "RuntimeDefault"

    def test_init_container_chown_not_in_command(self):
        """'chown' must not appear in initContainer command (F-14 gate: no CAP_CHOWN regression)."""
        manifest = _make_manifest()
        init = manifest["spec"]["initContainers"][0]
        cmd_str = " ".join(init["command"])
        assert "chown" not in cmd_str, (
            f"initContainer command must not contain 'chown' — kubelet fsGroup handles ownership: {cmd_str}"
        )


class TestPodFsGroupChangePolicy:
    """F-14: Pod-level fsGroupChangePolicy: OnRootMismatch."""

    def test_pod_fsgroup_change_policy_on_root_mismatch(self):
        """Pod securityContext has fsGroupChangePolicy=OnRootMismatch and fsGroup=10001 (F-14)."""
        manifest = _make_manifest()
        pod_sc = manifest["spec"]["securityContext"]
        assert pod_sc["fsGroup"] == 10001
        assert pod_sc.get("fsGroupChangePolicy") == "OnRootMismatch"
