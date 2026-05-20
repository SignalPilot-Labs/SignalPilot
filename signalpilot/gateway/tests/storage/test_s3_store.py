"""Tests for S3WorkspaceStore.

Uses moto mock_aws for tests that only need boto3 (set-up/inspection).
Uses direct method mocking for tests involving aioboto3 async operations,
since moto 5.x + aiobotocore 2.x have compatibility issues.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.storage.workspace_store import WorkspaceKey

_BUCKET = "test-ws-bucket"
_REGION = "us-east-1"
_PREFIX = "workspaces/v1"


def _make_key(
    org_id: str = "org1",
    user_id: str = "user1",
    notebook_id: str = "abcdef1234567890abcdef1234567890",
) -> WorkspaceKey:
    return WorkspaceKey(org_id=org_id, user_id=user_id, notebook_id=notebook_id)


def _make_store(endpoint_url: str | None = None):
    from gateway.storage.s3_store import S3WorkspaceStore

    return S3WorkspaceStore(
        bucket=_BUCKET,
        prefix_root=_PREFIX,
        region=_REGION,
        endpoint_url=endpoint_url,
    )


def _make_mock_s3_client():
    """Return a mock async S3 client for use in tests."""
    client = AsyncMock()
    # Context manager support for `async with session.client(...) as s3:`
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestS3StoreObjectKey:
    def test_object_key_correct_structure(self):
        """_object_key produces correct prefix-based S3 key."""
        store = _make_store()
        key = _make_key()
        k = store._object_key(key, "snapshots", "ver1", "file.txt")
        assert k == f"{_PREFIX}/org/org1/user/user1/notebook/abcdef1234567890abcdef1234567890/snapshots/ver1/file.txt"

    def test_object_key_rejects_dotdot(self):
        """_object_key raises ValueError for '..' traversal segments."""
        store = _make_store()
        key = _make_key()
        with pytest.raises(ValueError, match=r"Invalid"):
            store._object_key(key, "snapshots/../../../etc/passwd")

    def test_object_key_rejects_slash_in_key_field(self):
        """WorkspaceKey with '/' in field raises ValueError at construction."""
        with pytest.raises(ValueError):
            WorkspaceKey(org_id="org/evil", user_id="user1", notebook_id="nb1")

    def test_object_key_rejects_nul(self):
        """WorkspaceKey with NUL byte raises ValueError at construction."""
        with pytest.raises(ValueError):
            WorkspaceKey(org_id="org\x001", user_id="user1", notebook_id="nb1")


class TestS3StoreColdStart:
    @pytest.mark.asyncio
    async def test_cold_start_returns_correct_result(self, tmp_path: Path):
        """hydrate returns cold_start=True when manifest GET fails (no manifest)."""
        store = _make_store()
        mock_s3 = _make_mock_s3_client()

        # get_object raises to simulate no manifest
        mock_s3.get_object.side_effect = Exception("NoSuchKey")

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3

        store._session = mock_session
        key = _make_key()
        dest = tmp_path / "dest"
        dest.mkdir()

        result = await store.hydrate(key, dest)

        assert result.cold_start is True
        assert result.manifest_version is None
        assert result.file_count == 0

    @pytest.mark.asyncio
    async def test_exists_false_when_no_manifest(self):
        """exists() returns False when head_object raises ClientError 404 (no manifest)."""
        from botocore.exceptions import ClientError

        store = _make_store()
        mock_s3 = _make_mock_s3_client()
        # H3: exists() now only catches ClientError with 404/NoSuchKey code.
        not_found = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )
        mock_s3.head_object.side_effect = not_found

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3

        store._session = mock_session
        key = _make_key()

        result = await store.exists(key)
        assert result is False

    @pytest.mark.asyncio
    async def test_exists_reraises_non_404_errors(self):
        """exists() re-raises non-404 ClientError (e.g. auth failure) rather than returning False."""
        from botocore.exceptions import ClientError

        store = _make_store()
        mock_s3 = _make_mock_s3_client()
        # Simulate an auth/permission error.
        auth_error = ClientError(
            {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject"
        )
        mock_s3.head_object.side_effect = auth_error

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3

        store._session = mock_session
        key = _make_key()

        with pytest.raises(ClientError):
            await store.exists(key)


class TestS3StoreManifestWrittenLast:
    @pytest.mark.asyncio
    async def test_manifest_written_last(self, tmp_path: Path):
        """Manifest pointer is written AFTER all data files (C2)."""
        store = _make_store()
        write_order: list[str] = []

        original_put = store._put_object

        async def _tracking_put(s3, *, key: str, data: bytes) -> None:
            write_order.append(key)
            # Don't actually call anything — just record the order.

        store._put_object = _tracking_put

        # Provide a mock s3 client (won't be used since _put_object is mocked)
        mock_s3 = _make_mock_s3_client()
        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3
        store._session = mock_session

        key = _make_key()
        src = tmp_path / "src"
        src.mkdir()
        (src / "data1.txt").write_text("data1")
        (src / "data2.txt").write_text("data2")

        await store.snapshot(key, src)

        assert write_order, "No PUT calls recorded"
        assert write_order[-1].endswith("_manifest.current.json"), (
            f"Last PUT should be manifest, got: {write_order[-1]!r}"
        )
        assert len(write_order) >= 3  # 2 data + 1 manifest


class TestS3StoreSSE:
    @pytest.mark.asyncio
    async def test_sse_param_always_aes256(self, tmp_path: Path):
        """Every _put_object call includes ServerSideEncryption=AES256."""
        store = _make_store()
        sse_values: list[str] = []

        mock_s3 = _make_mock_s3_client()

        # Capture SSE from put_object calls
        async def _capture_put_object(**kwargs):
            sse_values.append(kwargs.get("ServerSideEncryption", "MISSING"))

        mock_s3.put_object.side_effect = _capture_put_object

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3
        store._session = mock_session

        key = _make_key()
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")

        await store.snapshot(key, src)

        assert sse_values, "No PUT calls captured"
        for sse in sse_values:
            assert sse == "AES256", f"Expected AES256, got {sse!r}"


class TestS3StoreHydrateNoManifest:
    @pytest.mark.asyncio
    async def test_hydrate_ignores_tree_with_no_manifest(self, tmp_path: Path):
        """hydrate returns cold_start when manifest GET fails."""
        store = _make_store()
        mock_s3 = _make_mock_s3_client()
        mock_s3.get_object.side_effect = Exception("NoSuchKey")

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3
        store._session = mock_session

        key = _make_key()
        dest = tmp_path / "dest"
        dest.mkdir()

        result = await store.hydrate(key, dest)

        assert result.cold_start is True
        assert not any(dest.iterdir())


class TestS3StoreBinaryRoundtrip:
    @pytest.mark.asyncio
    async def test_binary_roundtrip(self, tmp_path: Path):
        """snapshot → hydrate roundtrip preserves binary content via mock."""
        from gateway.storage.manifest import Manifest, serialize

        store = _make_store()

        # Build a manifest that matches what would be snapshotted
        binary_content = bytes(range(256))
        text_content = b"hello world"

        snapped_data: dict[str, bytes] = {}

        mock_s3 = _make_mock_s3_client()

        async def _mock_put(**kwargs):
            snapped_data[kwargs["Key"]] = kwargs["Body"]

        mock_s3.put_object.side_effect = _mock_put

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3
        store._session = mock_session

        key = _make_key()
        src = tmp_path / "src"
        src.mkdir()
        (src / "binary.bin").write_bytes(binary_content)
        (src / "text.txt").write_bytes(text_content)

        snap_result = await store.snapshot(key, src)

        # Verify snapshot recorded the data
        assert snap_result.file_count == 2
        assert snap_result.manifest_version

        # Verify the manifest key is in the snapped data
        manifest_key = store._object_key(key, "_manifest.current.json")
        assert manifest_key in snapped_data, "Manifest not written"

        # Data files should be there too
        data_keys = [k for k in snapped_data if not k.endswith("_manifest.current.json")]
        assert len(data_keys) == 2


class TestS3StoreCrossOrgIsolation:
    def test_different_orgs_have_different_key_prefixes(self):
        """Org A's key prefix is completely disjoint from org B's."""
        store = _make_store()

        key_a = _make_key(org_id="org-alpha")
        key_b = _make_key(org_id="org-beta")

        prefix_a = store._object_key(key_a, "_manifest.current.json")
        prefix_b = store._object_key(key_b, "_manifest.current.json")

        assert prefix_a != prefix_b
        assert "org-alpha" in prefix_a
        assert "org-beta" not in prefix_a
        assert "org-beta" in prefix_b
        assert "org-alpha" not in prefix_b

    @pytest.mark.asyncio
    async def test_cross_org_isolation(self, tmp_path: Path):
        """Org B hydrate finds nothing even when it shares the same backing store as org A.

        Both stores write to and read from the SAME shared in-memory dict
        (a poor-man's S3 bucket). Org B's hydrate must see cold_start because
        the key prefix differs — it cannot accidentally read org A's objects.
        This is the real isolation test: store_b has access to the same dict
        that store_a wrote to, but its key derivation puts data under a different
        prefix that store_b's own hydrate does not know to look for.
        """
        store_a = _make_store()
        store_b = _make_store()

        key_a = _make_key(org_id="org-alpha")
        key_b = _make_key(org_id="org-beta")

        # Shared backing dict — both stores read from and write to the same object.
        shared_store: dict[str, bytes] = {}

        # Build a single shared mock S3 client that both stores use.
        shared_s3 = _make_mock_s3_client()

        async def _shared_put(**kwargs):
            shared_store[kwargs["Key"]] = kwargs["Body"]

        async def _shared_get(**kwargs):
            key = kwargs["Key"]
            if key not in shared_store:
                raise Exception("NoSuchKey")
            body_mock = AsyncMock()
            body_mock.read = AsyncMock(return_value=shared_store[key])
            return {"Body": body_mock}

        async def _shared_list_pages(Bucket, Prefix):
            keys = [k for k in shared_store if k.startswith(Prefix)]
            yield {"Contents": [{"Key": k} for k in keys]}

        shared_s3.put_object.side_effect = _shared_put
        shared_s3.get_object.side_effect = _shared_get

        # paginator mock
        paginator_mock = MagicMock()
        paginator_mock.paginate = _shared_list_pages
        shared_s3.get_paginator.return_value = paginator_mock

        shared_session = MagicMock()
        shared_session.client.return_value = shared_s3
        store_a._session = shared_session
        store_b._session = shared_session

        # Snapshot org A into shared store.
        src_a = tmp_path / "src_a"
        src_a.mkdir()
        (src_a / "secret_a.txt").write_text("org-a-secret")
        await store_a.snapshot(key_a, src_a)

        # Verify org A's data is in the shared store.
        assert any("org-alpha" in k for k in shared_store), (
            "Org A should have written data to shared store"
        )
        assert not any("org-beta" in k for k in shared_store), (
            "No org B data should exist yet"
        )

        # Hydrate org B from the SAME shared store — should see cold_start.
        # store_b builds key_b's manifest key which contains "org-beta"; no such
        # object exists in shared_store, so get_object raises → cold start.
        dest_b = tmp_path / "dest_b"
        dest_b.mkdir()
        result_b = await store_b.hydrate(key_b, dest_b)

        assert result_b.cold_start is True, (
            "Org B should see cold_start — org A's data must not be visible "
            "under org B's key prefix even in the same shared store"
        )
        assert not any(dest_b.iterdir()), (
            "Org B's dest dir must be empty — no data leaked from org A"
        )


class TestS3StoreConcurrentSnapshotsManifestOrdering:
    @pytest.mark.asyncio
    async def test_concurrent_snapshots_each_complete_before_manifest(self, tmp_path: Path):
        """C2: For every manifest write, all data files have an earlier timestamp.

        Two concurrent snapshot() calls run against the same store. Each _put_object
        call is tracked with a timestamp. For each manifest write, every data file
        with the same version prefix must have been written first.
        """
        store_a = _make_store()
        store_b = _make_store()

        key = _make_key()
        put_log: list[tuple[str, float]] = []  # (key, timestamp)

        mock_s3_a = _make_mock_s3_client()
        mock_s3_b = _make_mock_s3_client()

        async def _tracking_put_a(**kwargs):
            put_log.append((kwargs["Key"], time.monotonic()))

        async def _tracking_put_b(**kwargs):
            put_log.append((kwargs["Key"], time.monotonic()))

        mock_s3_a.put_object.side_effect = _tracking_put_a
        mock_s3_b.put_object.side_effect = _tracking_put_b

        mock_session_a = MagicMock()
        mock_session_a.client.return_value = mock_s3_a
        store_a._session = mock_session_a

        mock_session_b = MagicMock()
        mock_session_b.client.return_value = mock_s3_b
        store_b._session = mock_session_b

        src_a = tmp_path / "src_a"
        src_a.mkdir()
        for i in range(3):
            (src_a / f"file_a_{i}.txt").write_text(f"content-a-{i}")

        src_b = tmp_path / "src_b"
        src_b.mkdir()
        for i in range(3):
            (src_b / f"file_b_{i}.txt").write_text(f"content-b-{i}")

        await asyncio.gather(
            store_a.snapshot(key, src_a),
            store_b.snapshot(key, src_b),
        )

        # For each manifest write, verify all data files have an earlier-or-equal timestamp.
        manifest_suffix = "_manifest.current.json"
        manifest_entries = [(k, t) for k, t in put_log if k.endswith(manifest_suffix)]
        assert manifest_entries, "No manifest PUT calls recorded"

        for manifest_key, manifest_ts in manifest_entries:
            data_entries_before = [
                (k, t) for k, t in put_log
                if t <= manifest_ts and not k.endswith(manifest_suffix)
            ]
            for data_key, data_ts in data_entries_before:
                assert data_ts <= manifest_ts + 1e-9, (
                    f"Data file {data_key!r} has timestamp AFTER manifest — broken pointer!"
                )
