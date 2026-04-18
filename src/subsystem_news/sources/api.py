"""Fixture-oriented JSON API source adapter."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from subsystem_news.contracts import NewsSourceConfig, SourceReference
from subsystem_news.errors import ContractViolationError
from subsystem_news.sources.base import (
    HttpTransport,
    NewsArticleRef,
    RawArticleFetch,
    UrllibHttpTransport,
    raw_content_hash,
    same_article_ref,
    trace_id_for,
    validate_response_url_within_source,
)


class ApiSourceAdapter:
    """Discover and fetch raw articles from a simple JSON articles array."""

    access_mode = "api"

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        del cursor
        articles = _load_articles(source, transport)
        return [_ref_for_article(source, article) for article in articles]

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> RawArticleFetch:
        for article in _load_articles(source, transport):
            article_ref = _ref_for_article(source, article)
            if same_article_ref(article_ref, ref):
                return _raw_fetch_from_article(source, article_ref, article)
        raise ContractViolationError(f"api article not found for source reference {ref.source_reference}")


def _load_articles(
    source: NewsSourceConfig,
    transport: HttpTransport | None,
) -> list[Mapping[str, Any]]:
    http = transport or UrllibHttpTransport()
    response = http.get(str(source.base_url))
    if response.status_code >= 400:
        raise ContractViolationError(f"api source returned status {response.status_code}")
    validate_response_url_within_source(response.url, source, adapter_name="api")

    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ContractViolationError("api source returned malformed JSON") from exc

    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list):
        raise ContractViolationError("api source JSON must contain an articles array")
    return [article for article in articles if isinstance(article, Mapping)]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _ref_for_article(source: NewsSourceConfig, article: Mapping[str, Any]) -> NewsArticleRef:
    provider_key = _optional_str(article.get("id"))
    url = _optional_str(article.get("url"))
    if provider_key is None and url is None:
        raise ContractViolationError("api article requires id or url")

    locator_type = "api_id" if provider_key is not None else "api_url"
    locator_value = provider_key or url
    source_reference = SourceReference.model_validate(
        {
            "source_id": source.source_id,
            "url": url,
            "provider_key": provider_key,
            "original_locator": {
                "locator_type": locator_type,
                "locator_value": locator_value,
            },
        }
    )
    return NewsArticleRef(
        source_id=source.source_id,
        source_reference=source_reference,
        url=url,
        provider_key=provider_key,
        title_hint=_optional_str(article.get("title")),
        published_at_hint=_parse_iso_datetime(_optional_str(article.get("published_at"))),
        cursor=provider_key or url,
    )


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _raw_fetch_from_article(
    source: NewsSourceConfig,
    ref: NewsArticleRef,
    article: Mapping[str, Any],
) -> RawArticleFetch:
    raw_title = _optional_str(article.get("title"))
    raw_body = _optional_str(article.get("body"))
    raw_html = _optional_str(article.get("html"))
    summary = _optional_str(article.get("summary"))
    published_at_raw = _optional_str(article.get("published_at"))
    author_or_channel = _optional_str(article.get("author_or_channel") or article.get("author"))
    fetched_at = datetime.now(timezone.utc)
    content_hash = raw_content_hash(
        {
            "source_reference": ref.source_reference,
            "raw_title": raw_title,
            "raw_body": raw_body,
            "raw_html": raw_html,
            "summary": summary,
            "published_at_raw": published_at_raw,
            "author_or_channel": author_or_channel,
        }
    )
    return RawArticleFetch(
        ref=ref,
        source=source,
        raw_title=raw_title,
        raw_body=raw_body,
        raw_html=raw_html,
        summary=summary,
        published_at_raw=published_at_raw,
        author_or_channel=author_or_channel,
        fetched_at=fetched_at,
        content_hash=content_hash,
        trace_id=trace_id_for(source.source_id, content_hash, fetched_at),
    )
