"""Minimal site HTML source adapter."""

from __future__ import annotations

import re
from html import unescape
from typing import Mapping

from subsystem_news.contracts import NewsSourceConfig, SourceReference, SourceReferenceLocator
from subsystem_news.sources.base import (
    HttpTransport,
    NewsArticleRef,
    RawArticleFetch,
    UrllibHttpTransport,
    content_hash_for,
    trace_id_for,
    utc_now,
)


class SiteHtmlSourceAdapter:
    """Adapter for an approved static HTML article URL."""

    access_mode = "site_html"

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        del cursor, transport
        source_reference = SourceReference(
            source_id=source.source_id,
            url=str(source.base_url),
            provider_key=None,
            original_locator=SourceReferenceLocator(
                locator_type="site_base_url",
                locator_value=str(source.base_url),
            ),
        )
        return [
            NewsArticleRef(
                source_id=source.source_id,
                source_reference=source_reference,
                url=str(source_reference.url),
                provider_key=None,
                title_hint=None,
                published_at_hint=None,
                cursor=str(source_reference.url),
            ),
        ]

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> RawArticleFetch:
        response = (transport or UrllibHttpTransport()).get(ref.url or str(source.base_url))
        raw_html = response.text
        raw_title = _title(raw_html)
        raw_body = _body_candidate(raw_html)
        content_hash = content_hash_for(
            {
                "raw_title": raw_title,
                "raw_body": raw_body,
                "raw_html": raw_html,
                "summary": None,
                "published_at_raw": None,
                "author_or_channel": source.display_name,
            },
        )
        fetched_at = utc_now()
        return RawArticleFetch(
            ref=ref,
            source=source,
            raw_title=raw_title,
            raw_body=raw_body,
            raw_html=raw_html,
            summary=None,
            published_at_raw=None,
            author_or_channel=source.display_name,
            fetched_at=fetched_at,
            content_hash=content_hash,
            trace_id=trace_id_for(ref, content_hash, fetched_at),
        )


def _title(html: str) -> str | None:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if match is None:
        return None
    title = unescape(match.group(1).strip())
    return title or None


def _body_candidate(html: str) -> str | None:
    match = re.search(r"(?is)<body[^>]*>(.*?)</body>", html)
    if match is None:
        return None
    body = match.group(1).strip()
    return body or None
