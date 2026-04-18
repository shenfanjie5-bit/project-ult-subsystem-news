from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from subsystem_news.errors import ContractViolationError
from subsystem_news.normalize.time_parse import parse_published_at


FETCHED_AT = datetime(2026, 1, 15, 10, 35, tzinfo=timezone.utc)


def test_parse_published_at_handles_iso_8601_and_returns_utc() -> None:
    parsed = parse_published_at("2026-01-15T10:30:00+08:00", fetched_at=FETCHED_AT)

    assert parsed == datetime(2026, 1, 15, 2, 30, tzinfo=timezone.utc)


def test_parse_published_at_handles_rfc_2822_pub_date() -> None:
    parsed = parse_published_at("Thu, 15 Jan 2026 10:30:00 GMT", fetched_at=FETCHED_AT)

    assert parsed == datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)


def test_parse_published_at_adds_default_timezone_to_naive_datetime() -> None:
    parsed = parse_published_at(
        datetime(2026, 1, 15, 10, 30),
        fetched_at=FETCHED_AT,
        default_tz=timezone(timedelta(hours=8)),
    )

    assert parsed == datetime(2026, 1, 15, 2, 30, tzinfo=timezone.utc)


def test_parse_published_at_uses_fetched_at_for_missing_values() -> None:
    assert parse_published_at(None, fetched_at=FETCHED_AT) == FETCHED_AT
    assert parse_published_at("  ", fetched_at=FETCHED_AT) == FETCHED_AT


def test_parse_published_at_rejects_malformed_timestamp_with_contract_error() -> None:
    with pytest.raises(ContractViolationError, match="invalid source timestamp"):
        parse_published_at("not-a-timestamp", fetched_at=FETCHED_AT)
