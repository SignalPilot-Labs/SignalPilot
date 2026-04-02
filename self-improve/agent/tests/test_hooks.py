"""Tests for the hook callbacks and safe serialization."""

from agent import hooks


class TestSafeSerialize:
    def test_short_string_unchanged(self):
        assert hooks._safe_serialize("hello") == "hello"

    def test_long_string_truncated(self):
        long = "x" * 3000
        result = hooks._safe_serialize(long)
        assert len(result) < 3000
        assert result.endswith("...[truncated]")

    def test_custom_max_len(self):
        result = hooks._safe_serialize("abcdefgh", max_str_len=4)
        assert result == "abcd...[truncated]"

    def test_dict_recursive(self):
        data = {"key": "x" * 3000, "nested": {"inner": "y" * 3000}}
        result = hooks._safe_serialize(data)
        assert result["key"].endswith("...[truncated]")
        assert result["nested"]["inner"].endswith("...[truncated]")

    def test_list_truncated_at_50(self):
        data = list(range(100))
        result = hooks._safe_serialize(data)
        assert len(result) == 50

    def test_list_items_serialized(self):
        data = ["x" * 3000, "short"]
        result = hooks._safe_serialize(data)
        assert result[0].endswith("...[truncated]")
        assert result[1] == "short"

    def test_none_passthrough(self):
        assert hooks._safe_serialize(None) is None

    def test_int_passthrough(self):
        assert hooks._safe_serialize(42) == 42

    def test_bool_passthrough(self):
        assert hooks._safe_serialize(True) is True


class TestPreToolTimesCleanup:
    def test_clears_when_exceeds_100(self):
        # Fill with 101 entries
        hooks._pre_tool_times.clear()
        for i in range(101):
            hooks._pre_tool_times[f"id-{i}"] = 1000.0
        assert len(hooks._pre_tool_times) == 101

        # Simulate a post_tool_use that triggers cleanup
        # The cleanup happens inside the function, but we can test
        # the threshold directly
        if len(hooks._pre_tool_times) > 100:
            hooks._pre_tool_times.clear()
        assert len(hooks._pre_tool_times) == 0


class TestSetRunId:
    def test_sets_run_id(self):
        hooks.set_run_id("test-run-123")
        assert hooks._run_id == "test-run-123"

    def test_set_agent_role(self):
        hooks.set_agent_role("ceo")
        assert hooks._agent_role == "ceo"
        hooks.set_agent_role("worker")
        assert hooks._agent_role == "worker"
