from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from subsystem_news.contracts import NewsSourceConfig, SourceReference
from subsystem_news.sources.base import NewsArticleRef, RawArticleFetch, raw_content_hash, trace_id_for


def source_config(source_id: str = "global-wire-rss") -> NewsSourceConfig:
    return NewsSourceConfig.model_validate(
        {
            "source_id": source_id,
            "display_name": "Global Wire RSS",
            "access_mode": "rss",
            "base_url": "https://news.example.com/rss",
            "approved": True,
            "reliability_tier": "A",
            "license_tag": "licensed-wire",
            "language": "en",
            "credential_ref": None,
        }
    )


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


def article_ref(source_id: str = "global-wire-rss") -> NewsArticleRef:
    return NewsArticleRef(
        source_id=source_id,
        source_reference=source_reference(source_id),
        title_hint="Acme signs contract",
        published_at_hint=datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc),
        cursor="wire-1",
    )


def test_raw_article_fetch_exposes_source_trace_and_raw_fields() -> None:
    ref = article_ref()
    fetched_at = datetime(2026, 1, 15, 10, 35, tzinfo=timezone.utc)
    content_hash = raw_content_hash(
        {
            "source_reference": ref.source_reference,
            "raw_title": "Acme signs contract",
            "raw_body": "Acme Corp announced a contract.",
        }
    )

    raw = RawArticleFetch(
        ref=ref,
        source=source_config(),
        raw_title="Acme signs contract",
        raw_body="Acme Corp announced a contract.",
        fetched_at=fetched_at,
        content_hash=content_hash,
        trace_id=trace_id_for(ref.source_id, content_hash, fetched_at),
    )

    assert raw.source_reference == ref.source_reference
    assert raw.source_id == "global-wire-rss"
    assert raw.title == "Acme signs contract"
    assert raw.published_at == ref.published_at_hint
    assert raw.license_tag == "licensed-wire"
    assert raw.reliability_tier == "A"


def test_raw_article_fetch_rejects_source_id_mismatch() -> None:
    ref = article_ref()

    with pytest.raises(ValidationError, match="source.source_id must match ref.source_id"):
        RawArticleFetch(
            ref=ref,
            source=source_config("other-source"),
            raw_body="Acme Corp announced a contract.",
            fetched_at=datetime(2026, 1, 15, 10, 35, tzinfo=timezone.utc),
            content_hash="sha256:raw",
            trace_id="fetch-1",
        )


def test_article_ref_rejects_malformed_source_reference() -> None:
    with pytest.raises(ValidationError):
        NewsArticleRef.model_validate(
            {
                "source_id": "global-wire-rss",
                "source_reference": {},
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "source_id": "   ",
            "url": "https://news.example.com/articles/1",
            "original_locator": {
                "locator_type": "rss_guid",
                "locator_value": "wire-1",
            },
        },
        {
            "source_id": "global-wire-rss",
            "provider_key": "   ",
            "original_locator": {
                "locator_type": "rss_guid",
                "locator_value": "wire-1",
            },
        },
        {
            "source_id": "global-wire-rss",
            "provider_key": "wire-1",
            "original_locator": {
                "locator_type": "   ",
                "locator_value": "wire-1",
            },
        },
        {
            "source_id": "global-wire-rss",
            "provider_key": "wire-1",
            "original_locator": {
                "locator_type": "rss_guid",
                "locator_value": "   ",
            },
        },
    ],
)
def test_source_reference_rejects_whitespace_only_trace_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SourceReference.model_validate(payload)
