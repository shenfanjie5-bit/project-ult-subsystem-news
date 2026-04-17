"""Publication timestamp parsing for raw article payloads."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from email.utils import parsedate_to_datetime


def _as_utc(value: datetime, default_tz: tzinfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=default_tz)
    return value.astimezone(timezone.utc)


def parse_published_at(
    value: str | datetime | None,
    *,
    fetched_at: datetime,
    default_tz: tzinfo = timezone.utc,
) -> datetime:
    """Parse source publication time and return a timezone-aware UTC datetime."""

    fetched_at_utc = _as_utc(fetched_at, default_tz)
    if value is None:
        return fetched_at_utc

    if isinstance(value, datetime):
        return _as_utc(value, default_tz)

    stripped = value.strip()
    if not stripped:
        return fetched_at_utc

    iso_value = stripped
    if iso_value.endswith("Z"):
        iso_value = f"{iso_value[:-1]}+00:00"

    try:
        return _as_utc(datetime.fromisoformat(iso_value), default_tz)
    except ValueError:
        pass

    parsed = parsedate_to_datetime(stripped)
    return _as_utc(parsed, default_tz)
