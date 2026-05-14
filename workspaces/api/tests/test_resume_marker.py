"""Unit tests for the approval resume-marker writer."""

from __future__ import annotations

import json
import stat
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest

from workspaces_api.agent.resume_marker import write_approval_marker

_RUN_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_APPROVAL_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
_DECIDED_AT = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
_DECISION: Literal["approved", "rejected"] = "approved"


def _ensure_resume_dir(tmp_path: Path, run_id: uuid.UUID = _RUN_ID) -> None:
    """Pre-create the resume dir (now required before write_approval_marker)."""
    resume_dir = tmp_path / str(run_id) / "home" / ".signalpilot" / "resume"
    resume_dir.mkdir(parents=True, mode=0o700, exist_ok=True)


def _call(tmp_path: Path, **overrides) -> Path:
    workdir_root = overrides.get("workdir_root", tmp_path)
    run_id = overrides.get("run_id", _RUN_ID)
    # Ensure resume dir exists (prepare_run_workdir responsibility in production)
    _ensure_resume_dir(workdir_root, run_id)
    kwargs = dict(
        workdir_root=tmp_path,
        run_id=_RUN_ID,
        approval_id=_APPROVAL_ID,
        decision=_DECISION,
        decided_at=_DECIDED_AT,
        comment=None,
    )
    kwargs.update(overrides)
    return write_approval_marker(**kwargs)  # type: ignore[arg-type]


class TestWriteApprovalMarker:
    def test_writes_file_at_expected_path(self, tmp_path: Path) -> None:
        path = _call(tmp_path)
        expected = (
            tmp_path
            / str(_RUN_ID)
            / "home"
            / ".signalpilot"
            / "resume"
            / f"{_APPROVAL_ID}.json"
        )
        assert path == expected
        assert path.exists()

    def test_resume_directory_must_exist_before_call(self, tmp_path: Path) -> None:
        """write_approval_marker raises FileNotFoundError if resume dir is absent.

        R8: lazy mkdir was removed; prepare_run_workdir must be called first.
        """
        # Do NOT pre-create the dir — call write_approval_marker directly.
        with pytest.raises(FileNotFoundError, match="resume dir missing"):
            write_approval_marker(
                workdir_root=tmp_path,
                run_id=_RUN_ID,
                approval_id=_APPROVAL_ID,
                decision=_DECISION,
                decided_at=_DECIDED_AT,
                comment=None,
            )

    def test_payload_shape(self, tmp_path: Path) -> None:
        path = _call(tmp_path, comment="looks good")
        data = json.loads(path.read_text())
        assert set(data.keys()) == {"approval_id", "decision", "decided_at", "comment"}
        assert data["approval_id"] == str(_APPROVAL_ID)
        assert data["decision"] in ("approved", "rejected")
        assert data["comment"] == "looks good"
        # decided_at is ISO 8601
        parsed = datetime.fromisoformat(data["decided_at"])
        assert parsed == _DECIDED_AT

    def test_payload_shape_approved(self, tmp_path: Path) -> None:
        path = _call(tmp_path, decision="approved")
        data = json.loads(path.read_text())
        assert data["decision"] == "approved"

    def test_payload_shape_rejected(self, tmp_path: Path) -> None:
        path = _call(tmp_path, decision="rejected")
        data = json.loads(path.read_text())
        assert data["decision"] == "rejected"

    def test_payload_null_comment(self, tmp_path: Path) -> None:
        path = _call(tmp_path, comment=None)
        data = json.loads(path.read_text())
        assert data["comment"] is None

    def test_atomic_overwrite_idempotent(self, tmp_path: Path) -> None:
        """Second write with different comment overwrites atomically."""
        _call(tmp_path, comment="first")
        path = _call(tmp_path, comment="second")
        data = json.loads(path.read_text())
        assert data["comment"] == "second"

    def test_file_mode_0o600(self, tmp_path: Path) -> None:
        path = _call(tmp_path)
        file_stat = path.stat()
        assert stat.S_IMODE(file_stat.st_mode) == 0o600

    def test_raises_oserror_when_resume_dir_unwritable(
        self, tmp_path: Path
    ) -> None:
        """If the resume dir exists but is unwritable, mkstemp raises OSError."""
        resume_dir = tmp_path / str(_RUN_ID) / "home" / ".signalpilot" / "resume"
        resume_dir.mkdir(parents=True, mode=0o555)
        with pytest.raises(OSError):
            write_approval_marker(
                workdir_root=tmp_path,
                run_id=_RUN_ID,
                approval_id=_APPROVAL_ID,
                decision=_DECISION,
                decided_at=_DECIDED_AT,
                comment=None,
            )

    def test_no_partial_file_on_concurrent_write(self, tmp_path: Path) -> None:
        """Multiple threads writing the same approval_id produce a valid final file."""
        errors: list[Exception] = []

        def _write(comment: str) -> None:
            try:
                _call(tmp_path, comment=comment)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write, args=(f"t{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        path = (
            tmp_path
            / str(_RUN_ID)
            / "home"
            / ".signalpilot"
            / "resume"
            / f"{_APPROVAL_ID}.json"
        )
        # File must be valid JSON
        data = json.loads(path.read_text())
        assert data["approval_id"] == str(_APPROVAL_ID)
