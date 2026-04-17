from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.sources.base import NewsArticleRef, RawArticleFetch


def source_reference(source_id: str = "global-wire-rss") -> SourceReference:
    return SourceReference.model_validate(
        {
            "source_id": source_id,
            "url": "https://news.example.com/articles/1",
            "provider_key": "wire-1",
            "original_locator": {
                "locator_type": "rss_guid",
                "locator_value": "wire-1",
            },
        }
    )


def test_raw_article_fetch_can_fill_trace_fields_from_article_ref() -> None:
    article_ref = NewsArticleRef(
        source_id="global-wire-rss",
        source_reference=source_reference(),
        title="Acme signs contract",
        published_at="2026-01-15T10:30:00Z",
        author_or_channel="Markets Desk",
        source_language="en",
    )

    raw = RawArticleFetch(
        article_ref=article_ref,
        fetched_at=datetime(2026, 1, 15, 10, 35, tzinfo=timezone.utc),
        license_tag="licensed-wire",
        reliability_tier="A",
        raw_body="Acme Corp announced a contract.",
    )

    assert raw.source_reference == article_ref.source_reference
    assert raw.source_id == "global-wire-rss"
    assert raw.title == "Acme signs contract"


def test_raw_article_fetch_rejects_source_id_mismatch() -> None:
    with pytest.raises(ValidationError, match="source_reference.source_id must match source_id"):
        RawArticleFetch(
            source_id="other-source",
            source_reference=source_reference(),
            fetched_at=datetime(2026, 1, 15, 10, 35, tzinfo=timezone.utc),
            license_tag="licensed-wire",
            reliability_tier="A",
            raw_body="Acme Corp announced a contract.",
        )
