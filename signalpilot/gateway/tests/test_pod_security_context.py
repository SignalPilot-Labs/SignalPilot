"""Tests for pod securityContext hardening (R3).

Verifies the _pod_manifest function produces a secure pod spec:
- Non-root user, seccomp RuntimeDefault, read-only root FS, drop ALL caps.
- emptyDir scratch volumes for /tmp, /home/notebook, /workspace.
- Required env vars: PYTHONDONTWRITEBYTECODE, HOME, SP_LOG_DIR.
- No host namespace mounts, no automounted SA token.
"""

from __future__ import annotations

import pytest


def _make_manifest(**kwargs) -> dict:
    """Build a pod manifest with minimal required args, allowing overrides."""
    from gateway.orchestrator.kubernetes import _pod_manifest

    defaults = {
        "pod_name": "nb-test",
        "namespace": "sp-nb-abc",
        "image": "signalpilot-notebook:latest",
        "user_id": "user-1",
        "org_id": "org-1",
        "project_id": None,
        "branch": "main",
        "gateway_url": "http://gateway:3300",
        "session_jwt_secret_name": "sp-jwt-sess-abc",
        "session_id": "sess-abc",
        "access_token": None,
    }
    defaults.update(kwargs)
    return _pod_manifest(**defaults)


class TestPodSecurityContext:
    def test_pod_runs_as_non_root(self):
        """Pod securityContext: runAsNonRoot=True, runAsUser/Group=10001, fsGroup=10001."""
        manifest = _make_manifest()
        pod_sc = manifest["spec"]["securityContext"]
        assert pod_sc["runAsNonRoot"] is True
        assert pod_sc["runAsUser"] == 10001
        assert pod_sc["runAsGroup"] == 10001
        assert pod_sc["fsGroup"] == 10001

    def test_pod_drops_all_caps_no_priv_escalation(self):
        """Container securityContext: drop ALL caps, allowPrivilegeEscalation=False."""
        manifest = _make_manifest()
        container_sc = manifest["spec"]["containers"][0]["securityContext"]
        assert container_sc["allowPrivilegeEscalation"] is False
        assert "ALL" in container_sc["capabilities"]["drop"]

    def test_pod_seccomp_runtime_default(self):
        """Pod-level seccompProfile: {type: RuntimeDefault}."""
        manifest = _make_manifest()
        pod_sc = manifest["spec"]["securityContext"]
        assert pod_sc["seccompProfile"]["type"] == "RuntimeDefault"

    def test_pod_readonly_rootfs_with_writable_scratch(self):
        """Container readOnlyRootFilesystem=True; emptyDir volumes for /tmp, /home/notebook, /workspace."""
        manifest = _make_manifest()
        container = manifest["spec"]["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True

        # Check volumes
        volumes = manifest["spec"]["volumes"]
        volume_names = {v["name"] for v in volumes}
        for expected in ("tmp", "home", "workspace"):
            assert expected in volume_names, f"Missing volume: {expected}"
            vol = next(v for v in volumes if v["name"] == expected)
            assert "emptyDir" in vol, f"Volume {expected} should be emptyDir"

        # Check volume mounts
        mounts = container["volumeMounts"]
        mount_paths = {m["mountPath"] for m in mounts}
        assert "/tmp" in mount_paths
        assert "/home/notebook" in mount_paths
        assert "/workspace" in mount_paths

    def test_pod_env_has_pythondontwritebytecode(self):
        """Pod env contains PYTHONDONTWRITEBYTECODE=1 (required for read-only root FS)."""
        manifest = _make_manifest()
        env = manifest["spec"]["containers"][0]["env"]
        env_dict = {e["name"]: e["value"] for e in env if "value" in e}
        assert "PYTHONDONTWRITEBYTECODE" in env_dict
        assert env_dict["PYTHONDONTWRITEBYTECODE"] == "1"

    def test_pod_env_has_log_dir_in_tmp(self):
        """Pod env contains SP_LOG_DIR pointing to a path under /tmp."""
        manifest = _make_manifest()
        env = manifest["spec"]["containers"][0]["env"]
        env_dict = {e["name"]: e["value"] for e in env if "value" in e}
        assert "SP_LOG_DIR" in env_dict
        assert env_dict["SP_LOG_DIR"].startswith("/tmp")

    def test_pod_env_has_home_in_home_notebook(self):
        """Pod env contains HOME=/home/notebook (writable emptyDir for UID 10001)."""
        manifest = _make_manifest()
        env = manifest["spec"]["containers"][0]["env"]
        env_dict = {e["name"]: e["value"] for e in env if "value" in e}
        assert "HOME" in env_dict
        assert env_dict["HOME"] == "/home/notebook"

    def test_pod_no_host_namespace_mounts(self):
        """Pod spec has no hostPath volumes, no hostNetwork/hostPID/hostIPC."""
        manifest = _make_manifest()
        spec = manifest["spec"]

        # No hostPath volumes.
        for vol in spec.get("volumes", []):
            assert "hostPath" not in vol, f"Found hostPath volume: {vol}"

        # No host namespace flags.
        assert not spec.get("hostNetwork", False)
        assert not spec.get("hostPID", False)
        assert not spec.get("hostIPC", False)

    def test_pod_automount_service_account_token_disabled(self):
        """Pod spec has automountServiceAccountToken: False."""
        manifest = _make_manifest()
        assert manifest["spec"]["automountServiceAccountToken"] is False
