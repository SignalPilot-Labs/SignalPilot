"""Tests for audit log rotation (MED-04 fix)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from signalpilot.gateway.gateway.store import _rotate_audit_if_needed


class TestAuditRotation:
    """Tests for audit log file rotation."""

    def _make_audit_file(self, tmp_dir: Path, size_bytes: int) -> Path:
        """Create a fake audit file of a specific size."""
        audit_file = tmp_dir / "audit.jsonl"
        # Write enough data to reach desired size
        line = json.dumps({"id": "test", "timestamp": 0, "event_type": "query"}) + "\n"
        lines_needed = max(1, size_bytes // len(line))
        audit_file.write_text(line * lines_needed)
        return audit_file

    def test_no_rotation_when_small(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audit_file = self._make_audit_file(tmp_path, 100)
            with patch("signalpilot.gateway.gateway.store.AUDIT_FILE", audit_file), \
                 patch("signalpilot.gateway.gateway.store._AUDIT_MAX_BYTES", 10_000):
                _rotate_audit_if_needed()
                assert audit_file.exists()
                assert not (tmp_path / "audit.jsonl.1").exists()

    def test_rotation_when_over_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audit_file = self._make_audit_file(tmp_path, 5000)
            rotated = tmp_path / "audit.jsonl.1"
            with patch("signalpilot.gateway.gateway.store.AUDIT_FILE", audit_file), \
                 patch("signalpilot.gateway.gateway.store._AUDIT_MAX_BYTES", 100):
                _rotate_audit_if_needed()
                # Original file should be renamed to .1
                assert not audit_file.exists()
                assert rotated.exists()

    def test_rotation_cascades(self):
        """When .1 exists, it should be moved to .2 before rotation."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audit_file = self._make_audit_file(tmp_path, 5000)
            # Create a pre-existing .1 file
            rotated_1 = tmp_path / "audit.jsonl.1"
            rotated_1.write_text("old rotated data\n")
            with patch("signalpilot.gateway.gateway.store.AUDIT_FILE", audit_file), \
                 patch("signalpilot.gateway.gateway.store._AUDIT_MAX_BYTES", 100):
                _rotate_audit_if_needed()
                rotated_2 = tmp_path / "audit.jsonl.2"
                # .2 should have the old .1 content
                assert rotated_2.exists()
                assert rotated_2.read_text() == "old rotated data\n"
                # .1 should have the current audit content
                assert rotated_1.exists()

    def test_no_file_no_error(self):
        """Rotation should be a no-op when the audit file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmp:
            nonexistent = Path(tmp) / "audit.jsonl"
            with patch("signalpilot.gateway.gateway.store.AUDIT_FILE", nonexistent):
                _rotate_audit_if_needed()  # Should not raise

    def test_old_rotation_deleted(self):
        """When .2 already exists, it should be deleted during cascading."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audit_file = self._make_audit_file(tmp_path, 5000)
            rotated_1 = tmp_path / "audit.jsonl.1"
            rotated_1.write_text("old .1\n")
            rotated_2 = tmp_path / "audit.jsonl.2"
            rotated_2.write_text("old .2 (will be deleted)\n")
            with patch("signalpilot.gateway.gateway.store.AUDIT_FILE", audit_file), \
                 patch("signalpilot.gateway.gateway.store._AUDIT_MAX_BYTES", 100):
                _rotate_audit_if_needed()
                # .2 should now contain old .1 content, not the old .2
                assert rotated_2.read_text() == "old .1\n"
