"""Terminal UI — monochrome, typographic, calm."""

import os
import sys
import threading
import time

# ANSI codes - disabled when not a TTY or SP_NO_COLOR=1
IS_TTY = sys.stdout.isatty() and os.environ.get("SP_NO_COLOR") != "1"
BOLD = "\033[1m" if IS_TTY else ""
DIM = "\033[2m" if IS_TTY else ""
GREEN = "\033[32m" if IS_TTY else ""
RED = "\033[31m" if IS_TTY else ""
RESET = "\033[0m" if IS_TTY else ""
CLEAR_LINE = "\033[2K" if IS_TTY else ""
CURSOR_UP = "\033[1A" if IS_TTY else ""


_BOX_WIDTH = 41  # inner content width


def box(lines: list[str]) -> None:
    """Print a monochrome box with left-aligned content lines."""
    w = _BOX_WIDTH
    bar = "─" * (w + 2)
    pad = " " * w
    print(f"  ┌{bar}┐")
    print(f"  │ {pad} │")
    for line in lines:
        print(f"  │ {line:<{w}} │")
        # Add a blank line after the title (first line)
        if line is lines[0] and len(lines) > 1:
            print(f"  │ {pad} │")
    print(f"  │ {pad} │")
    print(f"  └{bar}┘")


def header() -> None:
    """Print the branded install header."""
    print()
    box([
        "    s i g n a l p i l o t",
        "    Installer  v0.1.0",
        "    github.com/SignalPilot-Labs",
    ])
    print()


def section(title: str, step: int | None = None, total: int | None = None) -> None:
    """Print a section header with optional step counter."""
    if step is not None and total is not None:
        print(f"\n  {BOLD}{title}{RESET}  {DIM}[{step}/{total}]{RESET}\n")
    else:
        print(f"\n  {BOLD}{title}{RESET}\n")


def kv(key: str, value: str) -> None:
    """Print a key-value pair."""
    print(f"    {key:<20}{value}")


def check(label: str, detail: str = "") -> None:
    """Print a success check item."""
    detail_str = f"  {detail}" if detail else ""
    print(f"    {label:<18}{GREEN}✓{RESET}{detail_str}")


def fail(label: str, detail: str = "") -> None:
    """Print a failure item."""
    detail_str = f"  {detail}" if detail else ""
    print(f"    {label:<18}✗{detail_str}")


def wait_item(label: str, detail: str = "") -> None:
    """Print a waiting/in-progress item."""
    detail_str = f"  {detail}" if detail else ""
    print(f"    {label:<18}{DIM}◐{RESET}{detail_str}")


def dot(label: str, detail: str = "") -> None:
    """Print a pending dot item."""
    detail_str = f"  {detail}" if detail else ""
    print(f"    {label:<18}{DIM}·{RESET}{detail_str}")


def dim_text(text: str) -> str:
    return f"{DIM}{text}{RESET}"


def bold_text(text: str) -> str:
    return f"{BOLD}{text}{RESET}"


def hint(text: str) -> None:
    """Print a dim hint line."""
    print(f"    {DIM}{text}{RESET}")


def error_block(title: str, detail: str) -> None:
    """Print an error with context."""
    print(f"\n  {title}")
    print(f"    {DIM}{detail}{RESET}\n")


class Spinner:
    """Minimal background spinner."""

    _FRAMES = ("◒", "◐", "◓", "◑")

    def __init__(self, message: str = ""):
        self._message = message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "Spinner":
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        i = 0
        while not self._stop.is_set():
            frame = self._FRAMES[i % len(self._FRAMES)]
            sys.stdout.write(f"\r  {DIM}{frame}{RESET}  {self._message} ")
            sys.stdout.flush()
            i += 1
            self._stop.wait(0.12)

    def stop(self, clear: bool = True) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if clear:
            sys.stdout.write(f"\r{CLEAR_LINE}")
            sys.stdout.flush()


class Timer:
    """Simple elapsed time tracker."""

    def __init__(self) -> None:
        self._start: float = 0

    def start(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)

    def elapsed_display(self) -> str:
        ms = self.elapsed_ms()
        if ms < 1000:
            return f"{ms}ms"
        return f"{ms / 1000:.1f}s"
