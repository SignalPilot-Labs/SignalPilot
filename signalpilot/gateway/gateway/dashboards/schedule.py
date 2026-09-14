"""Refresh timing.

A dashboard refreshes every ``interval_minutes`` aligned to an anchor
wall-clock time in an IANA timezone. Daily and longer intervals fire at the
anchor; shorter intervals fire at anchor + k * interval for integer k. The
math runs in local wall-clock time and zoneinfo localizes the result, so
daylight-saving transitions shift the UTC instant with the local clock.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ALLOWED_INTERVALS = (15, 60, 120, 240, 480, 720, 1440)
DEFAULT_ANCHOR = "06:00"
DEFAULT_TIMEZONE = "UTC"

_ANCHOR_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_anchor(anchor_time: str | None) -> tuple[int, int]:
    """(hour, minute) of an "HH:MM" anchor; the default when missing or invalid."""
    match = _ANCHOR_RE.match((anchor_time or "").strip())
    if match is None:
        match = _ANCHOR_RE.match(DEFAULT_ANCHOR)
        assert match is not None
    return int(match.group(1)), int(match.group(2))


def valid_anchor(anchor_time: str | None) -> bool:
    return anchor_time is None or _ANCHOR_RE.match(anchor_time.strip()) is not None


def resolve_timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo((name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def valid_timezone(name: str | None) -> bool:
    if not name or not name.strip():
        return False
    try:
        ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False
    return True


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def compute_next_refresh_at(
    now_utc: datetime,
    interval_minutes: int | None,
    anchor_time: str | None,
    timezone: str | None,
) -> datetime | None:
    """The first refresh instant strictly after ``now_utc``, as an aware UTC datetime.

    None when ``interval_minutes`` is None (refresh off).
    """
    if interval_minutes is None:
        return None
    interval = max(1, int(interval_minutes))
    zone = resolve_timezone(timezone)
    hour, minute = parse_anchor(anchor_time)
    now = _aware_utc(now_utc)
    local_now = now.astimezone(zone)
    # Work on the naive local wall clock; localize at the end.
    wall_now = local_now.replace(tzinfo=None)
    anchor_today = wall_now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if interval >= 1440:
        candidate = anchor_today
        while _localize(candidate, zone) <= now:
            candidate += timedelta(days=1)
        return _localize(candidate, zone).astimezone(UTC)

    step = timedelta(minutes=interval)
    elapsed = wall_now - anchor_today
    steps = elapsed // step
    candidate = anchor_today + step * steps
    # Step back once in case the localized instant is already past now, then
    # walk forward until strictly after now (DST can move the instant).
    candidate -= step
    while _localize(candidate, zone) <= now:
        candidate += step
    return _localize(candidate, zone).astimezone(UTC)


def _localize(wall: datetime, zone: ZoneInfo) -> datetime:
    """Attach the zone to a naive wall-clock time. Gaps roll forward (fold=0)."""
    return wall.replace(tzinfo=zone)
