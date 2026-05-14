"""Tests for the signalpilot-resume-wait CLI.

Each test invokes main([...]) directly and captures stdout/stderr via capsys.
No FastAPI dependency — pure stdlib CLI.

Exit code contract:
  0   success
  64  data error (malformed JSON, bad payload)
  65  bad args (invalid UUID, out-of-range bounds)
  74  I/O error
  124 timeout
"""

from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from workspaces_agent_resume_wait.cli import main

_VALID_APPROVAL_ID = str(uuid.uuid4())
_OTHER_APPROVAL_ID = str(uuid.uuid4())


def _write_marker(
    path: Path,
    approval_id: str = _VALID_APPROVAL_ID,
    decision: str = "approved",
    decided_at: str = "2026-05-01T12:00:00+00:00",
    comment: str | None = None,
) -> None:
    payload = {
        "approval_id": approval_id,
        "decision": decision,
        "decided_at": decided_at,
        "comment": comment,
    }
    path.write_bytes(json.dumps(payload).encode())


class TestResumeWaitCLI:
    def test_marker_present_returns_decision(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 0; stdout is parseable JSON with decision == 'approved'."""
        approval_id = str(uuid.uuid4())
        _write_marker(tmp_path / f"{approval_id}.json", approval_id=approval_id)
        rc = main(["--resume-dir", str(tmp_path), approval_id])
        assert rc == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["decision"] == "approved"
        assert payload["approval_id"] == approval_id

    def test_marker_present_with_rejected_decision(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 0; decision == 'rejected'."""
        approval_id = str(uuid.uuid4())
        _write_marker(
            tmp_path / f"{approval_id}.json",
            approval_id=approval_id,
            decision="rejected",
        )
        rc = main(["--resume-dir", str(tmp_path), approval_id])
        assert rc == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["decision"] == "rejected"

    def test_marker_absent_blocks_until_timeout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 124; stderr contains 'timeout'; elapsed >= 0.25s and < 1.0s."""
        approval_id = str(uuid.uuid4())
        start = time.monotonic()
        rc = main(
            [
                "--resume-dir",
                str(tmp_path),
                "--timeout-seconds",
                "0.3",
                "--poll-interval-seconds",
                "0.05",
                approval_id,
            ]
        )
        elapsed = time.monotonic() - start
        assert rc == 124
        captured = capsys.readouterr()
        assert "timeout" in captured.err
        assert elapsed >= 0.25
        assert elapsed < 1.0

    def test_marker_appears_during_poll(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Thread writes marker after 0.15s; main() returns 0 with matching payload."""
        approval_id = str(uuid.uuid4())
        marker_path = tmp_path / f"{approval_id}.json"

        def _delayed_write() -> None:
            time.sleep(0.15)
            _write_marker(marker_path, approval_id=approval_id)

        with ThreadPoolExecutor(max_workers=1) as pool:
            writer_future = pool.submit(_delayed_write)
            rc = main(
                [
                    "--resume-dir",
                    str(tmp_path),
                    "--timeout-seconds",
                    "5.0",
                    "--poll-interval-seconds",
                    "0.05",
                    approval_id,
                ]
            )
            writer_future.result()

        assert rc == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["decision"] == "approved"
        assert payload["approval_id"] == approval_id

    def test_malformed_json_exits_64(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Truncated JSON file → exit 64 with 'malformed_json' on stderr."""
        approval_id = str(uuid.uuid4())
        (tmp_path / f"{approval_id}.json").write_bytes(b"{")
        rc = main(["--resume-dir", str(tmp_path), approval_id])
        assert rc == 64
        captured = capsys.readouterr()
        assert "malformed_json" in captured.err

    def test_missing_decision_field_exits_64(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Valid JSON without 'decision' → exit 64."""
        approval_id = str(uuid.uuid4())
        (tmp_path / f"{approval_id}.json").write_bytes(
            json.dumps(
                {"approval_id": approval_id, "decided_at": "2026-05-01T00:00:00+00:00"}
            ).encode()
        )
        rc = main(["--resume-dir", str(tmp_path), approval_id])
        assert rc == 64
        captured = capsys.readouterr()
        assert "malformed_json" in captured.err

    def test_invalid_decision_value_exits_64(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """'decision': 'maybe' → exit 64."""
        approval_id = str(uuid.uuid4())
        _write_marker(
            tmp_path / f"{approval_id}.json",
            approval_id=approval_id,
            decision="maybe",
        )
        rc = main(["--resume-dir", str(tmp_path), approval_id])
        assert rc == 64
        captured = capsys.readouterr()
        assert "malformed_json" in captured.err

    def test_approval_id_mismatch_exits_64(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """File approval_id differs from CLI arg → exit 64."""
        approval_id = str(uuid.uuid4())
        wrong_id = str(uuid.uuid4())
        # Write file under approval_id path but with wrong_id in payload
        _write_marker(
            tmp_path / f"{approval_id}.json",
            approval_id=wrong_id,
        )
        rc = main(["--resume-dir", str(tmp_path), approval_id])
        assert rc == 64
        captured = capsys.readouterr()
        assert "malformed_json" in captured.err

    def test_invalid_approval_id_arg_exits_65(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Non-UUID approval_id → exit 65, stderr contains 'bad_args'."""
        rc = main(["--resume-dir", str(tmp_path), "not-a-uuid"])
        assert rc == 65
        captured = capsys.readouterr()
        assert "bad_args" in captured.err

    def test_timeout_below_minimum_exits_65(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--timeout-seconds -1 → exit 65 (bounds check inside main()).

        Bounds validation runs after argparse, inside main(), so the exit code
        is always 65 (not argparse's exit 2).
        """
        approval_id = str(uuid.uuid4())
        rc = main(
            [
                "--resume-dir",
                str(tmp_path),
                "--timeout-seconds",
                "-1",
                approval_id,
            ]
        )
        assert rc == 65
        captured = capsys.readouterr()
        assert "bad_args" in captured.err
