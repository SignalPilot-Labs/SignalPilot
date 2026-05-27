"""Tests for LocalWorkspaceStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.storage.local_store import LocalWorkspaceStore
from gateway.storage.workspace_store import WorkspaceKey


def _make_key(
    org_id: str = "org1",
    user_id: str = "user1",
    notebook_id: str = "abcdef1234567890abcdef1234567890",
) -> WorkspaceKey:
    return WorkspaceKey(org_id=org_id, user_id=user_id, notebook_id=notebook_id)


class TestLocalStoreColdStart:
    @pytest.mark.asyncio
    async def test_cold_start_no_manifest(self, tmp_path: Path):
        """hydrate returns cold_start=True when no manifest exists."""
        store = LocalWorkspaceStore(root=tmp_path / "root")
        key = _make_key()
        dest = tmp_path / "dest"
        dest.mkdir()

        result = await store.hydrate(key, dest)

        assert result.cold_start is True
        assert result.manifest_version is None
        assert result.file_count == 0
        assert result.bytes_copied == 0
        assert not any(dest.iterdir())

    @pytest.mark.asyncio
    async def test_exists_returns_false_when_no_manifest(self, tmp_path: Path):
        """exists() returns False when no manifest is present."""
        store = LocalWorkspaceStore(root=tmp_path / "root")
        key = _make_key()
        assert not await store.exists(key)


class TestLocalStoreSnapshotHydrateRoundtrip:
    @pytest.mark.asyncio
    async def test_text_and_binary_roundtrip(self, tmp_path: Path):
        """snapshot → hydrate roundtrip preserves text and binary files."""
        store = LocalWorkspaceStore(root=tmp_path / "root")
        key = _make_key()

        # Create source dir with text + binary files.
        src = tmp_path / "src"
        src.mkdir()
        (src / "hello.txt").write_text("Hello, world!")
        (src / "data.bin").write_bytes(bytes(range(256)))
        subdir = src / "sub"
        subdir.mkdir()
        (subdir / "nested.py").write_text("# nested")

        result = await store.snapshot(key, src)

        assert result.file_count == 3
        assert result.bytes_uploaded > 0
        assert result.manifest_version
        assert result.skipped_paths == ()

        # Hydrate into a new dir.
        dest = tmp_path / "dest"
        dest.mkdir()
        hydrate_result = await store.hydrate(key, dest)

        assert hydrate_result.cold_start is False
        assert hydrate_result.manifest_version == result.manifest_version
        assert hydrate_result.file_count == 3

        # Verify file contents.
        assert (dest / "hello.txt").read_text() == "Hello, world!"
        assert (dest / "data.bin").read_bytes() == bytes(range(256))
        assert (dest / "sub" / "nested.py").read_text() == "# nested"

    @pytest.mark.asyncio
    async def test_exists_returns_true_after_snapshot(self, tmp_path: Path):
        """exists() returns True after at least one snapshot."""
        store = LocalWorkspaceStore(root=tmp_path / "root")
        key = _make_key()
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("data")
        await store.snapshot(key, src)
        assert await store.exists(key)


class TestLocalStoreAtomicReplace:
    @pytest.mark.asyncio
    async def test_manifest_pointer_written_last(self, tmp_path: Path):
        """Manifest pointer file exists only after all data files are written."""
        store = LocalWorkspaceStore(root=tmp_path / "root")
        key = _make_key()

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "b.txt").write_text("bbb")

        result = await store.snapshot(key, src)

        ws_root = (
            tmp_path / "root" / "org" / key.org_id / "user" / key.user_id
            / "notebook" / key.notebook_id
        )
        manifest_file = ws_root / "_manifest.current.json"
        snapshot_dir = ws_root / "snapshots" / result.manifest_version

        assert manifest_file.exists(), "Manifest pointer must exist after snapshot"
        assert snapshot_dir.exists(), "Snapshot directory must exist after snapshot"
        assert (snapshot_dir / "a.txt").exists()
        assert (snapshot_dir / "b.txt").exists()

    @pytest.mark.asyncio
    async def test_second_snapshot_replaces_manifest_pointer(self, tmp_path: Path):
        """Second snapshot updates the manifest pointer to the new version."""
        store = LocalWorkspaceStore(root=tmp_path / "root")
        key = _make_key()

        src = tmp_path / "src"
        src.mkdir()
        (src / "v1.txt").write_text("v1")
        r1 = await store.snapshot(key, src)

        (src / "v2.txt").write_text("v2")
        r2 = await store.snapshot(key, src)

        assert r1.manifest_version != r2.manifest_version

        # Hydrate — should get v2.
        dest = tmp_path / "dest"
        dest.mkdir()
        hr = await store.hydrate(key, dest)
        assert hr.manifest_version == r2.manifest_version
        assert (dest / "v2.txt").exists()


class TestLocalStoreOverSizeSkip:
    @pytest.mark.asyncio
    async def test_over_size_file_skipped(self, tmp_path: Path, monkeypatch):
        """Files over max_file_bytes are skipped and recorded in skipped_paths."""
        from gateway.storage import local_store as ls_mod

        monkeypatch.setattr(ls_mod, "MAX_FILE_BYTES", 10)

        store = LocalWorkspaceStore(root=tmp_path / "root")
        key = _make_key()
        src = tmp_path / "src"
        src.mkdir()
        (src / "small.txt").write_bytes(b"hi")
        (src / "big.bin").write_bytes(b"x" * 20)

        result = await store.snapshot(key, src)

        assert result.file_count == 1
        assert len(result.skipped_paths) == 1
        assert "big.bin" in result.skipped_paths[0]


class TestLocalStoreObjectKeyRejectsTraversal:
    @pytest.mark.asyncio
    async def test_dotdot_in_key_field_raises(self, tmp_path: Path):
        """WorkspaceKey with '..' raises ValueError at construction."""
        with pytest.raises(ValueError):
            WorkspaceKey(org_id="..", user_id="user1", notebook_id="nb1")


class TestLocalStoreSymlinkSkip:
    """V2: symlinks in the snapshot src are skipped to prevent exfil via symlink-following."""

    @pytest.mark.asyncio
    async def test_snapshot_skips_symlinks(self, tmp_path: Path):
        """Symlinks in src are not included in the snapshot (V2 security fix)."""
        store = LocalWorkspaceStore(root=tmp_path / "root")
        key = _make_key()

        src = tmp_path / "src"
        src.mkdir()
        (src / "real.txt").write_bytes(b"real content")

        # Create a symlink inside src pointing to a file outside.
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"host secret")
        (src / "evil_link.txt").symlink_to(secret)

        result = await store.snapshot(key, src)

        # Only the real file should be snapshotted; symlink excluded.
        assert result.file_count == 1, (
            f"Only 1 real file should be snapshotted, got {result.file_count}"
        )
        assert "evil_link.txt" not in result.skipped_paths, (
            "Symlink should be silently skipped, not recorded in skipped_paths"
        )

        # Verify the snapshot dir has only the real file.
        from gateway.storage.manifest import deserialize
        ws_root = (
            tmp_path / "root" / "org" / key.org_id / "user" / key.user_id
            / "notebook" / key.notebook_id
        )
        manifest = deserialize((ws_root / "_manifest.current.json").read_bytes())
        snapshot_dir = ws_root / "snapshots" / manifest.version
        snapped_files = [f.name for f in snapshot_dir.rglob("*") if f.is_file()]
        assert "real.txt" in snapped_files
        assert "evil_link.txt" not in snapped_files
