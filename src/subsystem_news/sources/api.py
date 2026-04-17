"""Fixture-oriented JSON API source adapter."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from subsystem_news.contracts import NewsSourceConfig, SourceReference, SourceReferenceLocator
from subsystem_news.errors import ContractViolationError
from subsystem_news.sources.base import (
    HttpTransport,
    NewsArticleRef,
    RawArticleFetch,
    UrllibHttpTransport,
    content_hash_for,
    trace_id_for,
    utc_now,
    validate_final_url,
)


class ApiSourceAdapter:
    """Lightweight JSON adapter for approved API fixtures."""

    access_mode = "api"

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        del cursor
        response = (transport or UrllibHttpTransport()).get(str(source.base_url))
        validate_final_url(response, source)
        return [_article_ref(source, article) for article in _articles(response.text)]

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> RawArticleFetch:
        response = (transport or UrllibHttpTransport()).get(str(source.base_url))
        validate_final_url(response, source)
        for article in _articles(response.text):
            candidate = _article_ref(source, article)
            if _same_ref(candidate, ref):
                return _article_fetch(ref, source, article)

        raise ContractViolationError(f"api article not found for source_reference: {ref.source_reference}")


def _articles(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractViolationError("api response is not valid JSON") from exc

    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list) or not all(isinstance(item, dict) for item in articles):
        raise ContractViolationError("api response requires an articles array")
    return articles


def _article_ref(source: NewsSourceConfig, article: Mapping[str, Any]) -> NewsArticleRef:
    provider_key = _optional_str(article.get("id"))
    url = _optional_str(article.get("url"))
    if provider_key is None and url is None:
        raise ContractViolationError("api article requires id or url")

    locator_type = "api_id" if provider_key is not None else "api_url"
    locator_value = provider_key or url
    source_reference = SourceReference(
        source_id=source.source_id,
        url=url,
        provider_key=provider_key,
        original_locator=SourceReferenceLocator(
            locator_type=locator_type,
            locator_value=locator_value or "",
        ),
    )
    return NewsArticleRef(
        source_id=source.source_id,
        source_reference=source_reference,
        url=str(source_reference.url) if source_reference.url is not None else None,
        provider_key=provider_key,
        title_hint=_optional_str(article.get("title")),
        published_at_hint=_parse_datetime(_optional_str(article.get("published_at"))),
        cursor=provider_key or url,
    )


def _article_fetch(
    ref: NewsArticleRef,
    source: NewsSourceConfig,
    article: Mapping[str, Any],
) -> RawArticleFetch:
    raw_title = _optional_str(article.get("title"))
    raw_body = _optional_str(article.get("body"))
    summary = _optional_str(article.get("summary"))
    published_at_raw = _optional_str(article.get("published_at"))
    author_or_channel = (
        _optional_str(article.get("author"))
        or _optional_str(article.get("channel"))
        or source.display_name
    )
    content_hash = content_hash_for(
        {
            "raw_title": raw_title,
            "raw_body": raw_body,
            "raw_html": None,
            "summary": summary,
            "published_at_raw": published_at_raw,
            "author_or_channel": author_or_channel,
        },
    )
    fetched_at = utc_now()
    return RawArticleFetch(
        ref=ref,
        source=source,
        raw_title=raw_title,
        raw_body=raw_body,
        raw_html=None,
        summary=summary,
        published_at_raw=published_at_raw,
        author_or_channel=author_or_channel,
        fetched_at=fetched_at,
        content_hash=content_hash,
        trace_id=trace_id_for(ref, content_hash, fetched_at),
    )


def _same_ref(left: NewsArticleRef, right: NewsArticleRef) -> bool:
    return (
        left.source_reference == right.source_reference
        or (left.provider_key is not None and left.provider_key == right.provider_key)
        or (left.url is not None and left.url == right.url)
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
