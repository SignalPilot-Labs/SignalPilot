"""Tests for workdir.py — create, cleanup, permissions, idempotent cleanup."""

from __future__ import annotations

import stat
import uuid
from pathlib import Path

import pytest

from workspaces_api.agent.workdir import (
    cleanup_run_workdir,
    prepare_resume_dir,
    prepare_run_workdir,
)

_STATIC_MD = "# Static CLAUDE.md for testing\n\nSome static instructions."
_PER_RUN_MD = "# Per-run CLAUDE.md\n\nRun-specific content."


class TestPrepareRunWorkdir:
    def test_creates_directory_tree(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4()
        workdir = prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)

        assert workdir.exists()
        assert (workdir / "home" / ".claude" / "CLAUDE.md").exists()
        assert (workdir / "home" / ".claude" / "CLAUDE_static.md").exists()

    def test_claude_md_content_matches(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4()
        workdir = prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)

        assert (workdir / "home" / ".claude" / "CLAUDE.md").read_text() == _PER_RUN_MD
        assert (
            workdir / "home" / ".claude" / "CLAUDE_static.md"
        ).read_text() == _STATIC_MD

    def test_directory_mode_is_0o700(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4()
        workdir = prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)

        run_mode = stat.S_IMODE(workdir.stat().st_mode)
        assert run_mode == 0o700

        home_mode = stat.S_IMODE((workdir / "home").stat().st_mode)
        assert home_mode == 0o700

    def test_resume_dir_created_with_mode_0o700(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4()
        workdir = prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)
        resume_dir = workdir / "home" / ".signalpilot" / "resume"
        assert resume_dir.is_dir()
        assert stat.S_IMODE(resume_dir.stat().st_mode) == 0o700

    def test_run_dir_named_by_run_id(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4()
        workdir = prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)
        assert workdir.name == str(run_id)

    def test_raises_if_already_exists(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4()
        prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)
        with pytest.raises(FileExistsError):
            prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)


class TestPrepareResumeDir:
    def test_creates_dir_with_mode_0o700(self, tmp_path: Path) -> None:
        result = prepare_resume_dir(tmp_path)
        assert result.is_dir()
        assert stat.S_IMODE(result.stat().st_mode) == 0o700

    def test_idempotent(self, tmp_path: Path) -> None:
        prepare_resume_dir(tmp_path)
        prepare_resume_dir(tmp_path)  # Should not raise

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        result = prepare_resume_dir(tmp_path)
        assert result == tmp_path / "home" / ".signalpilot" / "resume"


class TestCleanupRunWorkdir:
    def test_cleanup_removes_directory(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4()
        workdir = prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)
        assert workdir.exists()

        cleanup_run_workdir(workdir)
        assert not workdir.exists()

    def test_cleanup_is_idempotent_for_missing_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent-dir"
        cleanup_run_workdir(missing)  # Should not raise

    def test_cleanup_idempotent_after_first_cleanup(self, tmp_path: Path) -> None:
        run_id = uuid.uuid4()
        workdir = prepare_run_workdir(tmp_path, run_id, _PER_RUN_MD, _STATIC_MD)
        cleanup_run_workdir(workdir)
        cleanup_run_workdir(workdir)  # Should not raise
