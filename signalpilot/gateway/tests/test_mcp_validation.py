"""Tests for MCP input validation helpers."""

from __future__ import annotations

import pytest

from gateway.mcp.validation import _MODEL_NAME_RE


class TestModelNameRe:
    def test_model_name_re_rejects_empty_segments(self) -> None:
        assert _MODEL_NAME_RE.match("a..b") is None

    def test_model_name_re_accepts_three_segments(self) -> None:
        assert _MODEL_NAME_RE.match("db.schema.tbl") is not None

    def test_model_name_re_rejects_leading_dot(self) -> None:
        assert _MODEL_NAME_RE.match(".foo") is None

    def test_model_name_re_rejects_trailing_dot(self) -> None:
        assert _MODEL_NAME_RE.match("foo.") is None

    def test_model_name_re_accepts_single_segment(self) -> None:
        assert _MODEL_NAME_RE.match("my_model") is not None

    def test_model_name_re_accepts_two_segments(self) -> None:
        assert _MODEL_NAME_RE.match("schema.table") is not None

    def test_model_name_re_rejects_four_segments(self) -> None:
        assert _MODEL_NAME_RE.match("a.b.c.d") is None
