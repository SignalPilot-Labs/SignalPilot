"""Security tests for the dbt_project_validate MCP tool.

Verifies that:
- The tool does not accept a dbt_bin parameter (removed to prevent
  arbitrary command execution).
- The timeout parameter is clamped to a safe range (1-300 seconds).
- Non-absolute project_dir values are rejected.
- Path traversal via '..' segments in project_dir is rejected.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock, patch

from gateway.mcp_server import dbt_project_validate


class TestDbtProjectValidateSignature:
    def test_no_dbt_bin_parameter(self):
        """dbt_project_validate must not accept a dbt_bin parameter.

        Allowing callers to control the executable path is an arbitrary
        command execution vector.
        """
        sig = inspect.signature(dbt_project_validate)
        assert "dbt_bin" not in sig.parameters, (
            "dbt_bin must not be a parameter of dbt_project_validate — "
            "it opens an arbitrary command execution vulnerability"
        )

    def test_accepts_project_dir_and_timeout(self):
        """The tool signature must include project_dir and timeout parameters."""
        sig = inspect.signature(dbt_project_validate)
        assert "project_dir" in sig.parameters
        assert "timeout" in sig.parameters


class TestDbtProjectValidateTimeoutClamping:
    def test_timeout_clamped_to_max_300(self):
        """Passing timeout=99999 must result in the subprocess receiving at most 300s."""
        captured_timeout: list[int] = []

        def fake_validate(project_dir: str, timeout: int):
            captured_timeout.append(timeout)
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.degradation_mode = "ok"
            mock_result.parse_time_ms = 1.0
            mock_result.error_count = 0
            mock_result.warning_count = 0
            mock_result.errors = []
            mock_result.warnings = []
            mock_result.orphan_patches = []
            return mock_result

        with patch("gateway.mcp_server._validate_project", side_effect=fake_validate):
            with patch("gateway.mcp_server._format_validation_result", return_value="ok"):
                asyncio.run(dbt_project_validate(project_dir="/tmp", timeout=99999))

        assert len(captured_timeout) == 1
        assert captured_timeout[0] <= 300, (
            f"Expected timeout <= 300 but got {captured_timeout[0]}"
        )

    def test_timeout_clamped_to_min_1(self):
        """Passing timeout=0 or negative must result in at least 1s timeout."""
        captured_timeout: list[int] = []

        def fake_validate(project_dir: str, timeout: int):
            captured_timeout.append(timeout)
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.degradation_mode = "ok"
            mock_result.parse_time_ms = 1.0
            mock_result.error_count = 0
            mock_result.warning_count = 0
            mock_result.errors = []
            mock_result.warnings = []
            mock_result.orphan_patches = []
            return mock_result

        with patch("gateway.mcp_server._validate_project", side_effect=fake_validate):
            with patch("gateway.mcp_server._format_validation_result", return_value="ok"):
                asyncio.run(dbt_project_validate(project_dir="/tmp", timeout=0))

        assert len(captured_timeout) == 1
        assert captured_timeout[0] >= 1, (
            f"Expected timeout >= 1 but got {captured_timeout[0]}"
        )


class TestDbtProjectValidatePathValidation:
    def test_non_absolute_path_rejected(self):
        """Non-absolute project_dir must be rejected with an error message."""
        result = asyncio.run(dbt_project_validate(project_dir="relative/path", timeout=60))
        assert "Error" in result
        assert "absolute" in result.lower()

    def test_bare_filename_rejected(self):
        """A bare directory name (no leading slash) must be rejected."""
        result = asyncio.run(dbt_project_validate(project_dir="myproject", timeout=60))
        assert "Error" in result
        assert "absolute" in result.lower()

    def test_path_with_dotdot_rejected(self):
        """project_dir containing '..' segments must be rejected."""
        result = asyncio.run(
            dbt_project_validate(project_dir="/tmp/projects/../../../etc", timeout=60)
        )
        assert "Error" in result
        assert ".." in result or "traversal" in result.lower() or "segments" in result.lower()

    def test_dotdot_in_middle_rejected(self):
        """Path traversal with '..' anywhere in the path must be rejected."""
        result = asyncio.run(
            dbt_project_validate(project_dir="/tmp/../etc/passwd", timeout=60)
        )
        assert "Error" in result

    def test_empty_project_dir_rejected(self):
        """Empty or whitespace-only project_dir must be rejected."""
        result = asyncio.run(dbt_project_validate(project_dir="", timeout=60))
        assert "Error" in result

    def test_valid_absolute_path_not_rejected_by_validation(self):
        """A clean absolute path must pass validation (may fail for other reasons)."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.degradation_mode = "project_missing"
        mock_result.parse_time_ms = 0.0
        mock_result.error_count = 1
        mock_result.warning_count = 0
        mock_result.errors = ["project directory does not exist: /tmp/nonexistent-dbt-project"]
        mock_result.warnings = []
        mock_result.orphan_patches = []

        with patch("gateway.mcp_server._validate_project", return_value=mock_result):
            with patch("gateway.mcp_server._format_validation_result", return_value="# dbt parse validation\nStatus: ✗ project_missing\n"):
                result = asyncio.run(
                    dbt_project_validate(project_dir="/tmp/nonexistent-dbt-project", timeout=60)
                )

        # Should not be a path-validation error
        assert "absolute" not in result.lower() or "Status" in result
