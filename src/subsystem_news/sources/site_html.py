"""Static site HTML source adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Mapping

from subsystem_news.contracts import NewsSourceConfig, SourceReference
from subsystem_news.errors import ContractViolationError
from subsystem_news.sources.base import (
    HttpTransport,
    NewsArticleRef,
    RawArticleFetch,
    UrllibHttpTransport,
    raw_content_hash,
    trace_id_for,
)


class _TitleAndBodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._stack: list[str] = []
        self._title_parts: list[str] = []
        self._article_parts: list[str] = []
        self._body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self._stack.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index] == lower:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if "title" in self._stack:
            self._title_parts.append(data)
        if "article" in self._stack:
            self._article_parts.append(data)
        if "body" in self._stack:
            self._body_parts.append(data)

    @property
    def title(self) -> str | None:
        return _joined_or_none(self._title_parts)

    @property
    def body_candidate(self) -> str | None:
        return _joined_or_none(self._article_parts) or _joined_or_none(self._body_parts)


def _joined_or_none(parts: list[str]) -> str | None:
    value = " ".join(part.strip() for part in parts if part.strip()).strip()
    return value or None


class SiteHtmlSourceAdapter:
    """Discover and fetch a single approved static HTML page."""

    access_mode = "site_html"

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        del cursor, transport
        url = str(source.base_url)
        source_reference = SourceReference.model_validate(
            {
                "source_id": source.source_id,
                "url": url,
                "provider_key": None,
                "original_locator": {
                    "locator_type": "page_url",
                    "locator_value": url,
                },
            }
        )
        return [
            NewsArticleRef(
                source_id=source.source_id,
                source_reference=source_reference,
                url=url,
                provider_key=None,
                title_hint=None,
                published_at_hint=None,
                cursor=url,
            )
        ]

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> RawArticleFetch:
        if ref.url is None:
            raise ContractViolationError("site_html reference requires url")

        http = transport or UrllibHttpTransport()
        response = http.get(ref.url)
        if response.status_code >= 400:
            raise ContractViolationError(f"site_html source returned status {response.status_code}")

        parser = _TitleAndBodyParser()
        parser.feed(response.text)
        raw_title = parser.title or ref.title_hint
        raw_body = parser.body_candidate
        fetched_at = datetime.now(timezone.utc)
        content_hash = raw_content_hash(
            {
                "source_reference": ref.source_reference,
                "raw_title": raw_title,
                "raw_body": raw_body,
                "raw_html": response.text,
                "summary": None,
                "published_at_raw": None,
                "author_or_channel": None,
            }
        )
        return RawArticleFetch(
            ref=ref,
            source=source,
            raw_title=raw_title,
            raw_body=raw_body,
            raw_html=response.text,
            summary=None,
            published_at_raw=None,
            author_or_channel=None,
            fetched_at=fetched_at,
            content_hash=content_hash,
            trace_id=trace_id_for(source.source_id, content_hash, fetched_at),
        )
