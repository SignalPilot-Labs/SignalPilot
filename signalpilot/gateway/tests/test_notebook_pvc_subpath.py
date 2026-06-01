"""Tests for per-org/session PVC subPath isolation (NB-H-1).

Verifies that _workspace_subpath produces correctly isolated paths and that
_pod_manifest wires subPath onto the workspace volumeMount in PVC mode only.
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
        "org_id": "org-A",
        "project_id": None,
        "branch": "main",
        "gateway_url": "http://gateway:3300",
        "session_jwt_secret_name": "sp-jwt-sess-1",
        "session_id": "sess-1",
        "access_token": None,
    }
    defaults.update(kwargs)
    return _pod_manifest(**defaults)


def _workspace_mount(manifest: dict) -> dict:
    """Return the workspace volumeMount dict from the notebook container."""
    container = manifest["spec"]["containers"][0]
    mounts = container["volumeMounts"]
    return next(m for m in mounts if m["name"] == "workspace")


def _workspace_volume(manifest: dict) -> dict:
    """Return the workspace volume dict from the pod spec."""
    volumes = manifest["spec"]["volumes"]
    return next(v for v in volumes if v["name"] == "workspace")


class TestWorkspaceSubPath:
    def test_pvc_mode_sets_subpath_on_workspace_mount(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PVC mode: workspace volumeMount has subPath == 'org-A/sess-1'."""
        monkeypatch.setenv("SP_NOTEBOOK_PVC", "shared-pvc")

        manifest = _make_manifest(org_id="org-A", session_id="sess-1")

        mount = _workspace_mount(manifest)
        assert mount["subPath"] == "org-A/sess-1"

        volume = _workspace_volume(manifest)
        assert "persistentVolumeClaim" in volume
        assert volume["persistentVolumeClaim"]["claimName"] == "shared-pvc"

    def test_pvc_mode_org_id_is_outermost_segment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PVC subPath has org_id as the first path segment."""
        monkeypatch.setenv("SP_NOTEBOOK_PVC", "shared-pvc")

        manifest = _make_manifest(org_id="org-A", session_id="sess-1")

        mount = _workspace_mount(manifest)
        subpath = mount["subPath"]
        assert subpath.startswith("org-A/")
        assert "/" in subpath
        assert subpath.split("/")[0] == "org-A"

    def test_emptydir_mode_has_no_subpath(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without SP_NOTEBOOK_PVC, workspace mount has no subPath and volume is emptyDir."""
        monkeypatch.delenv("SP_NOTEBOOK_PVC", raising=False)

        manifest = _make_manifest(org_id="org-A", session_id="sess-1")

        mount = _workspace_mount(manifest)
        assert "subPath" not in mount

        volume = _workspace_volume(manifest)
        assert "emptyDir" in volume

    def test_subpath_sanitizes_path_traversal(self) -> None:
        """_workspace_subpath replaces unsafe chars; no dot segments; exactly one '/'."""
        from gateway.orchestrator.kubernetes import _workspace_subpath

        result = _workspace_subpath("../evil", "../../etc")

        assert "." not in result
        assert result.count("/") == 1
        segments = result.split("/")
        assert len(segments) == 2
        for segment in segments:
            assert segment == segment.replace(".", "_").replace("/", "_")

    def test_subpath_empty_org_id_raises(self) -> None:
        """_workspace_subpath raises ValueError when org_id is empty."""
        from gateway.orchestrator.kubernetes import _workspace_subpath

        with pytest.raises(ValueError, match="org_id"):
            _workspace_subpath("", "sess-1")

    def test_cross_org_subpaths_disjoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two orgs with identical session_id get disjoint workspace subPaths."""
        monkeypatch.setenv("SP_NOTEBOOK_PVC", "shared-pvc")

        manifest_a = _make_manifest(org_id="org-alpha", session_id="same-session")
        manifest_b = _make_manifest(org_id="org-beta", session_id="same-session")

        subpath_a = _workspace_mount(manifest_a)["subPath"]
        subpath_b = _workspace_mount(manifest_b)["subPath"]

        prefix_a = subpath_a.split("/")[0]
        prefix_b = subpath_b.split("/")[0]

        assert prefix_a != prefix_b, (
            f"Cross-org subPaths share common leading segment: {subpath_a!r} vs {subpath_b!r}"
        )
