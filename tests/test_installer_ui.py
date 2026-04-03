from unittest.mock import patch

import pytest

from signalpilot.gateway.gateway.installer import ui


# ---------------------------------------------------------------------------
# ui.header()
# ---------------------------------------------------------------------------

class TestUiHeader:
    """header() should print a multi-line branded box to stdout."""

    def test_prints_without_error(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        assert captured.out  # something was printed

    def test_output_contains_signalpilot_name(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        # The header renders the name spaced out: "s i g n a l p i l o t"
        assert "s i g n a l p i l o t" in captured.out.lower()

    def test_output_contains_box_characters(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        # The box uses Unicode box-drawing characters
        assert "┌" in captured.out or "─" in captured.out

    def test_output_contains_version(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        assert "v0.1.0" in captured.out

    def test_no_stderr_output(self, capsys):
        ui.header()
        captured = capsys.readouterr()
        assert captured.err == ""


# ---------------------------------------------------------------------------
# ui.section()
# ---------------------------------------------------------------------------

class TestUiSection:
    """section() should print the title with surrounding whitespace."""

    def test_title_appears_in_output(self, capsys):
        ui.section("Dependencies")
        captured = capsys.readouterr()
        assert "Dependencies" in captured.out

    def test_output_has_leading_whitespace(self, capsys):
        ui.section("System")
        captured = capsys.readouterr()
        # The format is "\n  {BOLD}title{RESET}\n"
        assert "  " in captured.out

    def test_no_stderr(self, capsys):
        ui.section("Anything")
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_different_titles_appear_correctly(self, capsys):
        for title in ("Building", "Starting services", "Configuration"):
            ui.section(title)
            captured = capsys.readouterr()
            assert title in captured.out


# ---------------------------------------------------------------------------
# ui.check()
# ---------------------------------------------------------------------------

class TestUiCheck:
    """check() should print the label and optional detail on one line."""

    def test_label_appears_in_output(self, capsys):
        ui.check("Docker Desktop")
        captured = capsys.readouterr()
        assert "Docker Desktop" in captured.out

    def test_detail_appears_when_provided(self, capsys):
        ui.check("Docker Desktop", "v24.0.5")
        captured = capsys.readouterr()
        assert "v24.0.5" in captured.out

    def test_no_detail_still_prints_label(self, capsys):
        ui.check("Git")
        captured = capsys.readouterr()
        assert "Git" in captured.out

    def test_check_mark_present(self, capsys):
        ui.check("Port 3200")
        captured = capsys.readouterr()
        assert "✓" in captured.out

    def test_no_stderr(self, capsys):
        ui.check("Something", "detail")
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_label_and_detail_on_same_line(self, capsys):
        ui.check("Port 3200", "available")
        captured = capsys.readouterr()
        lines = [l for l in captured.out.splitlines() if "Port 3200" in l]
        assert len(lines) == 1
        assert "available" in lines[0]


# ---------------------------------------------------------------------------
# ui.Spinner
# ---------------------------------------------------------------------------

class TestUiSpinner:
    """Spinner.start() / stop() lifecycle must be safe and non-blocking."""

    def test_start_returns_self(self):
        spinner = ui.Spinner("loading")
        returned = spinner.start()
        spinner.stop(clear=False)
        assert returned is spinner

    def test_stop_after_start_does_not_raise(self):
        spinner = ui.Spinner("loading")
        spinner.start()
        spinner.stop(clear=False)  # must not raise

    def test_thread_is_alive_after_start(self):
        spinner = ui.Spinner("loading")
        spinner.start()
        assert spinner._thread is not None
        assert spinner._thread.is_alive()
        spinner.stop(clear=False)

    def test_thread_is_stopped_after_stop(self):
        spinner = ui.Spinner("loading")
        spinner.start()
        spinner.stop(clear=False)
        # Give the thread a moment to finish (stop() joins with timeout=1)
        spinner._thread.join(timeout=2)
        assert not spinner._thread.is_alive()

    def test_stop_without_start_does_not_raise(self):
        spinner = ui.Spinner("loading")
        spinner.stop(clear=False)  # no thread started — must not raise

    def test_stop_sets_stop_event(self):
        spinner = ui.Spinner("loading")
        spinner.start()
        spinner.stop(clear=False)
        assert spinner._stop.is_set()

    def test_multiple_start_stop_cycles(self):
        spinner = ui.Spinner("loading")
        for _ in range(3):
            spinner.start()
            spinner.stop(clear=False)

    def test_default_message_stored(self):
        spinner = ui.Spinner("testing spinner")
        assert spinner._message == "testing spinner"

    def test_empty_message_is_valid(self):
        spinner = ui.Spinner()
        spinner.start()
        spinner.stop(clear=False)


# ---------------------------------------------------------------------------
# ui.Timer
# ---------------------------------------------------------------------------


class TestUiTimer:
    def test_start_returns_self(self):
        t = ui.Timer()
        assert t.start() is t

    def test_elapsed_ms_is_non_negative(self):
        t = ui.Timer().start()
        assert t.elapsed_ms() >= 0

    def test_elapsed_ms_increases_over_time(self):
        import time
        t = ui.Timer().start()
        time.sleep(0.05)
        assert t.elapsed_ms() >= 30  # allow some slack

    def test_elapsed_display_ms_format(self):
        t = ui.Timer().start()
        # Immediate — should be under 1000ms
        display = t.elapsed_display()
        assert display.endswith("ms")

    def test_elapsed_display_seconds_format(self):
        t = ui.Timer()
        t._start = 0  # fake a very old start time
        import time
        # Patch perf_counter to return a large value
        with patch("time.perf_counter", return_value=2.5):
            display = t.elapsed_display()
        assert display == "2.5s"


# ---------------------------------------------------------------------------
# ui.section() with step counters
# ---------------------------------------------------------------------------


class TestUiSectionSteps:
    def test_step_counter_appears(self, capsys):
        ui.section("Building", step=3, total=6)
        out = capsys.readouterr().out
        assert "[3/6]" in out
        assert "Building" in out

    def test_no_step_counter_when_none(self, capsys):
        ui.section("System")
        out = capsys.readouterr().out
        assert "System" in out
        assert "[" not in out

    def test_step_counter_zero_values(self, capsys):
        ui.section("Config", step=0, total=0)
        out = capsys.readouterr().out
        assert "[0/0]" in out
