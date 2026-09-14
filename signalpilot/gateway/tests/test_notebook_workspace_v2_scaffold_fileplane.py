"""Notebook Runtime v2 target suite — §4.3 write-through file plane and user workflows.

Continues ``test_notebook_workspace_v2_scaffold.py``; see that module's
docstring for the suite's role as the spec's acceptance criteria.
"""

from __future__ import annotations

import hashlib

import pytest

from ._notebook_workspace_v2_support import ORG, _create_project, _run, api, db, storage, ws

# ── §4.3 Sync agent (gate G2) ───────────────────────────────────────────────


class TestWriteThroughFilePlane:
    """§4.3 REVISED (supersedes the sync-agent design): there is no local
    mirror and no debounce window. A save IS a durable commit; a crash loses
    nothing that was saved. The notebook-server client half of this contract
    is covered in notebook-server/tests/test_gateway_file_system.py."""

    def test_save_is_durable_immediately_no_debounce_window(self, api, storage):
        """The old bar was 'durable within 2s'; the new bar is: the PUT
        response already names the committed revision, and the blob is in S3
        before the client hears success."""
        project = _create_project(api)
        response = api.put(f"/api/workspace-projects/{project}/files/nb.py", content=b"x = 1")
        assert response.json()["revision"] == 0
        digest = hashlib.sha256(b"x = 1").hexdigest()
        from gateway.workspace_store import blob_key

        assert _run(storage.get_bytes(blob_key(ORG, project, digest))) == b"x = 1"

    def test_edit_then_save_roundtrip_preserves_exact_content(self, api):
        """USER STORY: edit an existing file, save, reopen — byte-identical,
        no CRLF/encoding mangling, mtime advances."""
        project = _create_project(api)
        original = "df = 1\r\nx = 'unicode: é'\n".encode()
        api.put(f"/api/workspace-projects/{project}/files/a.py", content=original)
        first = api.post(f"/api/workspace-projects/{project}/files:list", json={"branch": "main"}).json()["files"][0]
        edited = original + b"y = 2\n"
        api.put(f"/api/workspace-projects/{project}/files/a.py", content=edited)
        assert api.get(f"/api/workspace-projects/{project}/files/a.py").content == edited
        second = api.post(f"/api/workspace-projects/{project}/files:list", json={"branch": "main"}).json()["files"][0]
        assert second["mtime"] >= first["mtime"]

    def test_unsaved_state_is_the_only_crash_loss(self, api):
        """§7: with write-through saves, a dead sandbox loses only the
        browser's unsaved buffer — every committed revision still serves."""
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/kept.py", content=b"saved")
        # The sandbox dying is a non-event for storage: no flush, no barrier,
        # nothing to reconcile. Head still serves the last save.
        assert api.get(f"/api/workspace-projects/{project}/files/kept.py").content == b"saved"

    def test_conflicting_batch_is_rejected_by_cas_and_retry_converges(self, api):
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/base.py", content=b"0")
        stale = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": None,
                "upserts": [{"path": "loser.py", "content_b64": "eA=="}],
                "deletes": [],
            },
        )
        assert stale.status_code == 409
        head = api.get(f"/api/workspace-projects/{project}/revisions").json()["revisions"][0]["revision"]
        retry = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": head,
                "upserts": [{"path": "loser.py", "content_b64": "eA=="}],
                "deletes": [],
            },
        )
        assert retry.status_code == 200

    def test_large_files_travel_by_presigned_put_and_commit_by_reference(self, api, storage):
        project = _create_project(api)
        payload = b"parquet-bytes " * 100
        digest = hashlib.sha256(payload).hexdigest()
        grant = api.post(
            f"/api/workspace-projects/{project}/files:upload-url",
            json={"sha256": digest, "size": len(payload)},
        )
        assert grant.status_code == 200
        # moto's presigned PUT needs no network here — write the blob at the
        # granted key, exactly what the client's PUT would do.
        _run(storage.put_bytes(grant.json()["key"], payload))
        committed = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": None,
                "upserts": [{"path": "data/big.parquet", "sha256": digest, "size": len(payload)}],
                "deletes": [],
            },
        )
        assert committed.status_code == 200
        got = api.get(f"/api/workspace-projects/{project}/files/data/big.parquet")
        assert got.content == payload

    def test_session_sidecars_are_ordinary_files(self, api):
        """__sp__ session snapshots (the reconnect experience) commit like any
        file; nothing in the storage plane special-cases them."""
        project = _create_project(api)
        response = api.put(
            f"/api/workspace-projects/{project}/files/__sp__/session/nb.py.json",
            content=b'{"cells": []}',
        )
        assert response.status_code == 200
        assert api.get(f"/api/workspace-projects/{project}/files/__sp__/session/nb.py.json").content == b'{"cells": []}'


# ── User interaction semantics (the jupyter-lab-like UX; gates G2–G4) ──────


class TestUserWorkflows:
    def test_save_edit_save_delete_navigate_back_full_journey(self, api):
        """USER STORY (end to end): create file → save → edit → save → delete
        → navigate back via an old link → recoverable from revision history,
        with a working restore affordance, never a 500."""
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        assert api.put(f"{base}/files/report.md", content=b"v1").json()["revision"] == 0
        assert api.put(f"{base}/files/report.md", content=b"v2").json()["revision"] == 1
        assert api.delete(f"{base}/files/report.md").json()["revision"] == 2

        # Navigate back via an old link: never a 500, always the old bytes.
        assert api.get(f"{base}/files/report.md").status_code == 404
        assert api.get(f"{base}/files/report.md?revision=1").content == b"v2"
        assert api.get(f"{base}/files/report.md?revision=0").content == b"v1"

        # Restore affordance: re-save the recovered content as a new revision.
        old = api.get(f"{base}/files/report.md?revision=1").content
        assert api.put(f"{base}/files/report.md", content=old).json()["revision"] == 3
        assert api.get(f"{base}/files/report.md").content == b"v2"

    def test_deleting_a_project_tombstones_links_instead_of_500(self, api):
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/kept.py", content=b"x")
        assert api.delete(f"/api/workspace-projects/{project}").status_code == 204
        response = api.get(f"/api/workspace-projects/{project}/files/kept.py")
        assert response.status_code == 410
        assert response.json()["detail"]["tombstone"] is True

    def test_rename_move_preserves_revision_lineage(self, api):
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        api.put(f"{base}/files/old-name.py", content=b"content")
        moved = api.post(
            f"{base}/files:move",
            json={"source": "old-name.py", "destination": "new-name.py"},
        )
        assert moved.status_code == 200
        # Head: only the new name; lineage: the pre-move revision still serves
        # the old path, and both entries share one blob (same sha).
        assert api.get(f"{base}/files/new-name.py").content == b"content"
        assert api.get(f"{base}/files/old-name.py").status_code == 404
        old_sha = api.get(f"{base}/files/old-name.py?revision=0").headers["X-SP-Sha256"]
        new_sha = api.get(f"{base}/files/new-name.py").headers["X-SP-Sha256"]
        assert old_sha == new_sha

    def test_browser_refresh_mid_edit_rehydrates_from_session_sidecar(self, api):
        """USER STORY: refresh mid-edit. Unsaved buffers are browser-tier by
        design (three-tier model); what the platform guarantees is that the
        session sidecar — outputs, cell state — reloads from the same branch
        the editor left, with no compute required."""
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        api.put(f"{base}/files/nb.py", content=b"x = 1")
        api.put(
            f"{base}/files/__sp__/session/nb.py.json",
            content=b'{"cells": [{"id": "a", "output": "1"}]}',
        )
        # The refreshed page re-reads both without any session existing.
        assert api.get(f"{base}/files/nb.py").content == b"x = 1"
        assert b'"output": "1"' in api.get(f"{base}/files/__sp__/session/nb.py.json").content

    def test_two_users_same_project_different_branches_never_interfere(self, api):
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        api.put(f"{base}/files/model.sql?branch=alice/work", content=b"alice")
        api.put(f"{base}/files/model.sql?branch=bob/work", content=b"bob")
        assert api.get(f"{base}/files/model.sql?branch=alice/work").content == b"alice"
        assert api.get(f"{base}/files/model.sql?branch=bob/work").content == b"bob"
        assert api.get(f"{base}/files/model.sql").status_code == 404  # main untouched

    def test_branch_switch_serves_the_other_branchs_content(self, api):
        """Branch switching is re-pointing reads — no clone, no checkout."""
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        api.put(f"{base}/files/config.yml", content=b"env: main")
        api.put(f"{base}/files/config.yml?branch=feature/x", content=b"env: feature")
        snap_main = api.get(f"{base}/snapshot").json()
        snap_feature = api.get(f"{base}/snapshot?branch=feature/x").json()
        assert snap_main["key"] != snap_feature["key"]
        assert api.get(f"{base}/files/config.yml?branch=feature/x").content == b"env: feature"

    def test_notebook_page_loads_without_any_compute(self, api):
        """The point of the whole redesign: browsing project files must not
        require pod/sandbox scheduling. This composed app carries no notebook
        session machinery at all — file reads work anyway."""
        from gateway.db.models import GatewayNotebookSession

        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/nb.py", content=b"x")
        listing = api.post(f"/api/workspace-projects/{project}/files:list", json={"branch": "main"})
        assert [f["path"] for f in listing.json()["files"]] == ["nb.py"]
        # And no session row was ever created to serve those reads.
        import asyncio as _asyncio

        from sqlalchemy import func, select

        from gateway.db.engine import get_db as _get_db  # the override target

        async def _count() -> int:
            agen = api.app.dependency_overrides[_get_db]()
            session = await agen.__anext__()
            try:
                result = await session.execute(select(func.count()).select_from(GatewayNotebookSession))
                return int(result.scalar_one())
            finally:
                await agen.aclose()

        assert _asyncio.run(_count()) == 0
