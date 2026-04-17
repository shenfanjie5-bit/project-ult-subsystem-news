"""RSS and Atom source adapter."""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Mapping
from xml.etree import ElementTree

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
)


class RssSourceAdapter:
    """Adapter for RSS and Atom feeds."""

    access_mode = "rss"

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        del cursor
        response = (transport or UrllibHttpTransport()).get(str(source.base_url))
        entries = _feed_entries(response.text)
        return [_entry_ref(source, entry, index) for index, entry in enumerate(entries)]

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> RawArticleFetch:
        response = (transport or UrllibHttpTransport()).get(str(source.base_url))
        for index, entry in enumerate(_feed_entries(response.text)):
            candidate = _entry_ref(source, entry, index)
            if _same_ref(candidate, ref):
                return _entry_fetch(ref, source, entry)

        raise ContractViolationError(f"rss article not found for source_reference: {ref.source_reference}")


def _feed_entries(xml_text: str) -> list[ElementTree.Element]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ContractViolationError("rss feed is not well-formed XML") from exc

    if _local_name(root.tag) == "feed":
        return [child for child in root if _local_name(child.tag) == "entry"]

    channel = next((child for child in root if _local_name(child.tag) == "channel"), root)
    return [child for child in channel if _local_name(child.tag) == "item"]


def _entry_ref(source: NewsSourceConfig, entry: ElementTree.Element, index: int) -> NewsArticleRef:
    title = _child_text(entry, "title")
    link = _entry_link(entry)
    provider_key = _child_text(entry, "guid") or _child_text(entry, "id")
    published_raw = (
        _child_text(entry, "pubDate")
        or _child_text(entry, "published")
        or _child_text(entry, "updated")
    )
    published_at = _parse_datetime(published_raw)
    locator_type = "rss_guid" if provider_key else "rss_link"
    locator_value = provider_key or link
    if locator_value is None:
        raise ContractViolationError("rss item requires guid/id or link")

    source_reference = SourceReference(
        source_id=source.source_id,
        url=link,
        provider_key=provider_key,
        original_locator=SourceReferenceLocator(
            locator_type=locator_type,
            locator_value=locator_value,
        ),
    )
    return NewsArticleRef(
        source_id=source.source_id,
        source_reference=source_reference,
        url=str(source_reference.url) if source_reference.url is not None else None,
        provider_key=provider_key,
        title_hint=title,
        published_at_hint=published_at,
        cursor=provider_key or link or str(index),
    )


def _entry_fetch(
    ref: NewsArticleRef,
    source: NewsSourceConfig,
    entry: ElementTree.Element,
) -> RawArticleFetch:
    raw_title = _child_text(entry, "title")
    raw_body = _child_text(entry, "encoded") or _child_text(entry, "content")
    summary = _child_text(entry, "description") or _child_text(entry, "summary")
    published_at_raw = (
        _child_text(entry, "pubDate")
        or _child_text(entry, "published")
        or _child_text(entry, "updated")
    )
    author_or_channel = (
        _child_text(entry, "author") or _child_text(entry, "creator") or source.display_name
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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ElementTree.Element, local_name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == local_name and child.text is not None:
            value = child.text.strip()
            return value or None
        if _local_name(child.tag) == local_name and list(child):
            nested = _child_text(child, "name")
            if nested is not None:
                return nested
    return None


def _entry_link(entry: ElementTree.Element) -> str | None:
    text_link = _child_text(entry, "link")
    if text_link is not None:
        return text_link
    for child in entry:
        if _local_name(child.tag) == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        pass

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
