"""Snapshot and sweep contracts for the scratch file capture."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

import pytest

from signalpilot._server.api.endpoints.chat_files.capture import (
    Fingerprint,
    ScratchFileCapture,
    is_captured_path,
    max_file_bytes,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _capture(scratch: Path, **kwargs: object) -> ScratchFileCapture:
    return ScratchFileCapture(
        scratch=scratch, run_id="run-1", **kwargs  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("artifacts/x.png", True),
        ("artifacts/nested/x.csv", True),
        ("report.md", True),
        ("analysis.py", False),
        ("scripts/helper.py", True),
        (".gateway-token", False),
        (".claude/settings.json", False),
        ("artifacts/.hidden.png", False),
        ("__pycache__/x.pyc", False),
        ("artifacts/__pycache__/x.pyc", False),
        ("dbt-target/manifest.json", False),
        ("dbt-logs/dbt.log", False),
        ("dbt-profiles/profiles.yml", False),
        ("dbt-stub.duckdb", False),
        ("artifacts/data.duckdb", True),
        ("artifacts/run.log", False),
        ("", False),
        ("/abs/x.png", False),
        ("../x.png", False),
    ],
)
def test_ignore_rules(path: str, expected: bool) -> None:
    assert is_captured_path(path) is expected


@pytest.mark.asyncio
async def test_baseline_on_empty_and_populated_scratch(
    tmp_path: Path,
) -> None:
    empty = _capture(tmp_path / "missing")
    await empty.baseline()
    assert empty.snapshot == {}
    assert await empty.sweep(reason="tool", tool_call_id=None) == []

    _write(tmp_path / "artifacts" / "old.png", b"old")
    _write(tmp_path / "analysis.py", b"import marimo\n")
    _write(tmp_path / ".gateway-token", b"secret")
    capture = _capture(tmp_path)
    await capture.baseline()
    assert set(capture.snapshot) == {"artifacts/old.png"}
    fingerprint = capture.snapshot["artifacts/old.png"]
    assert isinstance(fingerprint, Fingerprint)
    assert fingerprint.size == 3
    # Baseline files are not artifacts of this run.
    assert await capture.sweep(reason="tool", tool_call_id="t1") == []


@pytest.mark.asyncio
async def test_sweep_returns_new_changed_unchanged_and_deleted(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "artifacts" / "keep.csv", b"a,b\n")
    capture = _capture(tmp_path)
    await capture.baseline()

    _write(tmp_path / "artifacts" / "chart.png", b"\x89PNG-1")
    first = await capture.sweep(reason="tool", tool_call_id="t1")
    assert [file.path for file in first] == ["artifacts/chart.png"]
    assert first[0].data == b"\x89PNG-1"
    assert first[0].content_hash == hashlib.sha256(b"\x89PNG-1").hexdigest()
    assert first[0].deleted is False
    assert first[0].size == 6

    # Unchanged files are not returned again.
    assert await capture.sweep(reason="tool", tool_call_id="t2") == []

    # A changed file with a different size is returned with new bytes.
    _write(tmp_path / "artifacts" / "chart.png", b"\x89PNG-2-longer")
    changed = await capture.sweep(reason="tool", tool_call_id="t3")
    assert [file.path for file in changed] == ["artifacts/chart.png"]
    assert changed[0].data == b"\x89PNG-2-longer"

    # A same-size rewrite with a newer mtime is a change too.
    target = tmp_path / "artifacts" / "chart.png"
    _write(target, b"\x89PNG-3-longer")
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000))
    same_size = await capture.sweep(reason="tool", tool_call_id="t4")
    assert [file.path for file in same_size] == ["artifacts/chart.png"]

    # Deleting a file yields a deleted marker with no bytes.
    (tmp_path / "artifacts" / "keep.csv").unlink()
    deleted = await capture.sweep(reason="run_end", tool_call_id=None)
    assert [(file.path, file.deleted) for file in deleted] == [
        ("artifacts/keep.csv", True)
    ]
    assert deleted[0].data == b""
    assert "artifacts/keep.csv" not in capture.snapshot
    assert await capture.sweep(reason="run_end", tool_call_id=None) == []


@pytest.mark.asyncio
async def test_sweep_skips_ignored_paths_and_symlinks(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    await capture.baseline()
    _write(tmp_path / "notebook.py", b"print(1)\n")
    _write(tmp_path / ".claude" / "state.json", b"{}")
    _write(tmp_path / "__pycache__" / "x.pyc", b"x")
    _write(tmp_path / "dbt-target" / "manifest.json", b"{}")
    _write(tmp_path / "dbt-logs" / "dbt.log", b"log")
    _write(tmp_path / "artifacts" / "trace.log", b"log")
    _write(tmp_path / "artifacts" / "table.csv", b"a\n1\n")
    try:
        (tmp_path / "artifacts" / "link.csv").symlink_to(
            tmp_path / "artifacts" / "table.csv"
        )
    except (OSError, NotImplementedError):
        pass

    captured = await capture.sweep(reason="tool", tool_call_id="t1")
    assert [file.path for file in captured] == ["artifacts/table.csv"]


@pytest.mark.asyncio
async def test_size_cap_skips_large_files_until_they_change(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path, max_bytes=8)
    await capture.baseline()
    _write(tmp_path / "artifacts" / "big.bin", b"x" * 9)
    _write(tmp_path / "artifacts" / "small.bin", b"x" * 8)

    captured = await capture.sweep(reason="tool", tool_call_id="t1")
    assert [file.path for file in captured] == ["artifacts/small.bin"]
    # The oversize file is remembered so it is not re-read every sweep.
    assert "artifacts/big.bin" in capture.snapshot
    assert await capture.sweep(reason="tool", tool_call_id="t2") == []

    _write(tmp_path / "artifacts" / "big.bin", b"y" * 4)
    shrunk = await capture.sweep(reason="tool", tool_call_id="t3")
    assert [file.path for file in shrunk] == ["artifacts/big.bin"]


def test_size_cap_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SP_CHAT_FILE_MAX_BYTES", raising=False)
    assert max_file_bytes() == 25 * 1024 * 1024
    monkeypatch.setenv("SP_CHAT_FILE_MAX_BYTES", "1024")
    assert max_file_bytes() == 1024
    monkeypatch.setenv("SP_CHAT_FILE_MAX_BYTES", "nope")
    assert max_file_bytes() == 25 * 1024 * 1024
    monkeypatch.setenv("SP_CHAT_FILE_MAX_BYTES", "0")
    assert max_file_bytes() == 25 * 1024 * 1024


@pytest.mark.asyncio
async def test_secret_refusal_drops_the_path_from_the_snapshot(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path, redactions=("run-token-secret", ""))
    await capture.baseline()
    _write(tmp_path / "artifacts" / "leak.txt", b"Bearer run-token-secret")
    _write(tmp_path / "artifacts" / "clean.txt", b"fine")

    captured = await capture.sweep(reason="tool", tool_call_id="t1")
    assert [file.path for file in captured] == ["artifacts/clean.txt"]
    assert "artifacts/leak.txt" not in capture.snapshot

    # Once the secret is gone the file is captured on the next sweep.
    _write(tmp_path / "artifacts" / "leak.txt", b"redacted")
    recovered = await capture.sweep(reason="tool", tool_call_id="t2")
    assert [file.path for file in recovered] == ["artifacts/leak.txt"]


@pytest.mark.asyncio
async def test_forget_makes_the_next_sweep_read_the_file_again(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    await capture.baseline()
    _write(tmp_path / "artifacts" / "x.csv", b"1\n")
    assert len(await capture.sweep(reason="tool", tool_call_id="t1")) == 1
    capture.forget("artifacts/x.csv")
    again = await capture.sweep(reason="run_end", tool_call_id=None)
    assert [file.path for file in again] == ["artifacts/x.csv"]


@pytest.mark.asyncio
async def test_adopted_scratch_files_are_not_re_uploaded(
    tmp_path: Path,
) -> None:
    """A later turn baselines the previous turn's files and skips them."""
    _write(tmp_path / "artifacts" / "turn1.png", b"png-1")
    _write(tmp_path / "analysis.py", b"import marimo\n")
    _write(tmp_path / ".gateway-token", b"token-2")
    turn_two = _capture(tmp_path)
    await turn_two.baseline()

    assert await turn_two.sweep(reason="tool", tool_call_id="t1") == []
    _write(tmp_path / "artifacts" / "turn2.csv", b"a\n")
    captured = await turn_two.sweep(reason="tool", tool_call_id="t2")
    assert [file.path for file in captured] == ["artifacts/turn2.csv"]
