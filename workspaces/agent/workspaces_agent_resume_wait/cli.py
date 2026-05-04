"""signalpilot-resume-wait — approval-marker consumer CLI.

Blocks until the approval resume-marker file for the given approval_id appears,
validates it, and prints the decision JSON on stdout.

Exit codes:
  0   — success; JSON payload printed on stdout
  64  — data error (malformed JSON, missing/invalid fields, ID mismatch)
  65  — bad arguments (invalid UUID, out-of-range timeout/poll-interval)
  74  — I/O error (unexpected OSError reading the marker file)
  124 — timeout (marker did not appear within --timeout-seconds)

Usage:
  signalpilot-resume-wait <approval_id> [--timeout-seconds N]
                          [--resume-dir PATH] [--poll-interval-seconds N]
  python -m workspaces_agent_resume_wait <approval_id> ...

The marker file written by the host API has this shape:
  {"approval_id":"<uuid>","decision":"approved"|"rejected",
   "decided_at":"<iso8601>","comment":"<str>"|null}

The writer uses os.replace (atomic rename), so a successful os.stat means
the file is fully populated. We do NOT retry on partial reads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

_MIN_TIMEOUT = 0.1
_MAX_TIMEOUT = 86400.0
_MIN_POLL_INTERVAL = 0.01
_MAX_POLL_INTERVAL = 5.0
_VALID_DECISIONS = {"approved", "rejected"}
_MAX_MARKER_BYTES = 64 * 1024
_REQUIRED_KEYS = {"approval_id", "decision", "decided_at"}

_EX_OK = 0
_EX_DATAERR = 64
_EX_USAGE = 65
_EX_IOERR = 74
_EX_TIMEOUT = 124


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="signalpilot-resume-wait",
        description="Block until an approval resume-marker appears; print decision JSON.",
    )
    parser.add_argument("approval_id", help="UUID of the approval to wait for.")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=1800.0,
        metavar="N",
        help="Maximum seconds to wait before exiting 124. Default: 1800.",
    )
    parser.add_argument(
        "--resume-dir",
        type=Path,
        default=Path.home() / ".signalpilot" / "resume",
        metavar="PATH",
        help="Directory containing resume-marker files. Default: ~/.signalpilot/resume",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=0.1,
        metavar="N",
        help="Polling interval in seconds. Default: 0.1",
    )
    return parser.parse_args(argv)


def _validate_uuid(value: str) -> uuid.UUID | None:
    """Return parsed UUID or None on failure."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _validate_bounds(
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> str | None:
    """Return an error message string if any bound is violated, else None."""
    if not (_MIN_TIMEOUT <= timeout_seconds <= _MAX_TIMEOUT):
        return (
            f"--timeout-seconds must be between {_MIN_TIMEOUT} and {_MAX_TIMEOUT},"
            f" got {timeout_seconds}"
        )
    if not (_MIN_POLL_INTERVAL <= poll_interval_seconds <= _MAX_POLL_INTERVAL):
        return (
            f"--poll-interval-seconds must be between {_MIN_POLL_INTERVAL}"
            f" and {_MAX_POLL_INTERVAL}, got {poll_interval_seconds}"
        )
    return None


def _validate_payload(
    payload: object,
    expected_approval_id: str,
) -> str | None:
    """Return an error message string if payload is invalid, else None."""
    if not isinstance(payload, dict):
        return "payload is not a JSON object"

    missing = _REQUIRED_KEYS - payload.keys()
    if missing:
        return f"missing required keys: {sorted(missing)}"

    if payload["decision"] not in _VALID_DECISIONS:
        return (
            f"invalid decision value: {payload['decision']!r};"
            f" expected one of {sorted(_VALID_DECISIONS)}"
        )

    if not isinstance(payload["decided_at"], str):
        return "decided_at must be a string"

    if str(payload["approval_id"]) != expected_approval_id:
        return (
            f"approval_id mismatch: file has {payload['approval_id']!r},"
            f" expected {expected_approval_id!r}"
        )

    return None


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    parsed_uuid = _validate_uuid(args.approval_id)
    if parsed_uuid is None:
        print("bad_args", file=sys.stderr)
        return _EX_USAGE

    bound_error = _validate_bounds(args.timeout_seconds, args.poll_interval_seconds)
    if bound_error is not None:
        print(f"bad_args: {bound_error}", file=sys.stderr)
        return _EX_USAGE

    marker_path = Path(args.resume_dir) / f"{args.approval_id}.json"
    deadline = time.monotonic() + args.timeout_seconds

    while True:
        try:
            os.stat(marker_path)
        except FileNotFoundError:
            if time.monotonic() >= deadline:
                print("timeout", file=sys.stderr)
                return _EX_TIMEOUT
            time.sleep(args.poll_interval_seconds)
            continue
        except OSError as exc:
            print(f"oserror: {type(exc).__name__}", file=sys.stderr)
            return _EX_IOERR

        # stat succeeded — writer used os.replace, file is fully present
        try:
            with marker_path.open("rb") as f:
                data = f.read(_MAX_MARKER_BYTES + 1)
            if len(data) > _MAX_MARKER_BYTES:
                print("malformed_json: marker exceeds size cap", file=sys.stderr)
                return _EX_DATAERR
        except OSError as exc:
            print(f"oserror: {type(exc).__name__}", file=sys.stderr)
            return _EX_IOERR

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            print("malformed_json", file=sys.stderr)
            return _EX_DATAERR

        validation_error = _validate_payload(payload, args.approval_id)
        if validation_error is not None:
            print(f"malformed_json: {validation_error}", file=sys.stderr)
            return _EX_DATAERR

        print(json.dumps(payload, separators=(",", ":")))
        return _EX_OK


if __name__ == "__main__":
    sys.exit(main())
