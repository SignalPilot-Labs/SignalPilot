#!/usr/bin/env python3
"""Poll source files and restart a development process on changes."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


WATCH_SUFFIXES = {".py", ".toml"}
IGNORED_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def snapshot(root: Path) -> dict[str, int]:
    files: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix not in WATCH_SUFFIXES:
                continue
            try:
                files[str(path)] = path.stat().st_mtime_ns
            except FileNotFoundError:
                continue
    return files


def stop_process(process: subprocess.Popen[object], timeout: float = 10.0) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command after --")

    watch_root = Path(args.watch)
    process: subprocess.Popen[object] | None = None

    def start() -> subprocess.Popen[object]:
        print(f"[dev-watch] starting: {' '.join(command)}", flush=True)
        return subprocess.Popen(command)

    def shutdown(signum: int, _frame: object) -> None:
        del signum
        if process is not None:
            stop_process(process)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    process = start()
    previous = snapshot(watch_root)
    while True:
        time.sleep(args.interval)
        current = snapshot(watch_root)
        changed = current != previous
        exited = process.poll() is not None

        if changed or exited:
            reason = "source change" if changed else f"exit {process.returncode}"
            print(f"[dev-watch] restarting after {reason}", flush=True)
            stop_process(process)
            previous = current
            process = start()


if __name__ == "__main__":
    sys.exit(main())
