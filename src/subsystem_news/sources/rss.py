"""RSS and Atom source adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape
from typing import Mapping
from xml.etree import ElementTree

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


@dataclass(frozen=True)
class _FeedEntry:
    ref: NewsArticleRef
    raw_title: str | None
    raw_body: str | None
    raw_html: str | None
    summary: str | None
    published_at_raw: str | None
    author_or_channel: str | None


_HTML_TAG_PATTERN = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*)?/?>")


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, local_name: str) -> ElementTree.Element | None:
    for child in element:
        if _local_name(child.tag) == local_name:
            return child
    return None


def _child_text(element: ElementTree.Element, local_name: str) -> str | None:
    return _text(_child(element, local_name))


def _classify_content(content: str | None) -> tuple[str | None, str | None]:
    if content is None:
        return None, None
    if _HTML_TAG_PATTERN.search(content):
        return None, content
    return content, None


def _serialize_markup(element: ElementTree.Element) -> str:
    tag = _local_name(element.tag)
    attrs = "".join(
        f' {_local_name(name)}="{escape(value, quote=True)}"'
        for name, value in element.attrib.items()
    )
    parts = [f"<{tag}{attrs}>"]
    if element.text is not None:
        parts.append(escape(element.text))
    for child in element:
        parts.append(_serialize_markup(child))
        if child.tail is not None:
            parts.append(escape(child.tail))
    parts.append(f"</{tag}>")
    return "".join(parts)


def _inner_markup(element: ElementTree.Element) -> str | None:
    parts: list[str] = []
    if element.text is not None:
        parts.append(escape(element.text))
    for child in element:
        parts.append(_serialize_markup(child))
        if child.tail is not None:
            parts.append(escape(child.tail))
    markup = "".join(parts).strip()
    return markup or None


def _content_fields(element: ElementTree.Element | None) -> tuple[str | None, str | None]:
    if element is None:
        return None, None
    if len(element) > 0:
        return None, _inner_markup(element)
    return _classify_content(_text(element))


def _first_content_fields(
    element: ElementTree.Element,
    local_names: tuple[str, ...],
) -> tuple[str | None, str | None]:
    for local_name in local_names:
        raw_body, raw_html = _content_fields(_child(element, local_name))
        if raw_body is not None or raw_html is not None:
            return raw_body, raw_html
    return None, None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _atom_link(entry: ElementTree.Element) -> str | None:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        rel = child.attrib.get("rel")
        href = child.attrib.get("href")
        if href and (rel is None or rel == "alternate"):
            return href
    return None


class RssSourceAdapter:
    """Discover and fetch raw articles from RSS or Atom feeds."""

    access_mode = "rss"

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        del cursor
        return [entry.ref for entry in self._load_entries(source, transport=transport)]

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> RawArticleFetch:
        for entry in self._load_entries(source, transport=transport):
            if _same_ref(entry.ref, ref):
                return _raw_fetch_from_entry(entry, source)
        raise ContractViolationError(f"rss entry not found for source reference {ref.source_reference}")

    def _load_entries(
        self,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None,
    ) -> list[_FeedEntry]:
        http = transport or UrllibHttpTransport()
        response = http.get(str(source.base_url))
        if response.status_code >= 400:
            raise ContractViolationError(f"rss source returned status {response.status_code}")

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:
            raise ContractViolationError("rss source returned malformed XML") from exc

        entries = list(_rss_entries(root, source))
        if entries:
            return entries
        return list(_atom_entries(root, source))


def _rss_entries(root: ElementTree.Element, source: NewsSourceConfig) -> list[_FeedEntry]:
    entries: list[_FeedEntry] = []
    channel = _child(root, "channel")
    channel_title = _child_text(channel if channel is not None else root, "title")
    for item in root.findall(".//item"):
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        guid = _child_text(item, "guid")
        pub_date = _child_text(item, "pubDate") or _child_text(item, "published")
        description = _child_text(item, "description")
        raw_body, raw_html = _first_content_fields(item, ("encoded", "content"))
        author = _child_text(item, "author") or _child_text(item, "creator") or channel_title
        provider_key = guid or link
        if provider_key is None and link is None:
            continue
        source_reference = SourceReference.model_validate(
            {
                "source_id": source.source_id,
                "url": link,
                "provider_key": provider_key,
                "original_locator": {
                    "locator_type": "rss_guid" if guid is not None else "rss_link",
                    "locator_value": guid or link,
                },
            }
        )
        entries.append(
            _FeedEntry(
                ref=NewsArticleRef(
                    source_id=source.source_id,
                    source_reference=source_reference,
                    url=link,
                    provider_key=provider_key,
                    title_hint=title,
                    published_at_hint=_parse_datetime(pub_date),
                    cursor=guid or link,
                ),
                raw_title=title,
                raw_body=raw_body,
                raw_html=raw_html,
                summary=description,
                published_at_raw=pub_date,
                author_or_channel=author,
            )
        )
    return entries


def _atom_entries(root: ElementTree.Element, source: NewsSourceConfig) -> list[_FeedEntry]:
    entries: list[_FeedEntry] = []
    feed_title = _child_text(root, "title")
    for entry in root.iter():
        if _local_name(entry.tag) != "entry":
            continue
        title = _child_text(entry, "title")
        link = _atom_link(entry)
        entry_id = _child_text(entry, "id")
        published = _child_text(entry, "published") or _child_text(entry, "updated")
        summary = _child_text(entry, "summary")
        raw_body, raw_html = _content_fields(_child(entry, "content"))
        author_element = _child(entry, "author")
        author = _child_text(author_element if author_element is not None else entry, "name") or feed_title
        provider_key = entry_id or link
        if provider_key is None and link is None:
            continue
        source_reference = SourceReference.model_validate(
            {
                "source_id": source.source_id,
                "url": link,
                "provider_key": provider_key,
                "original_locator": {
                    "locator_type": "atom_id" if entry_id is not None else "atom_link",
                    "locator_value": entry_id or link,
                },
            }
        )
        entries.append(
            _FeedEntry(
                ref=NewsArticleRef(
                    source_id=source.source_id,
                    source_reference=source_reference,
                    url=link,
                    provider_key=provider_key,
                    title_hint=title,
                    published_at_hint=_parse_datetime(published),
                    cursor=entry_id or link,
                ),
                raw_title=title,
                raw_body=raw_body,
                raw_html=raw_html,
                summary=summary,
                published_at_raw=published,
                author_or_channel=author,
            )
        )
    return entries


def _same_ref(left: NewsArticleRef, right: NewsArticleRef) -> bool:
    return (
        left.source_reference == right.source_reference
        or (
            left.provider_key is not None
            and right.provider_key is not None
            and left.provider_key == right.provider_key
        )
        or (left.url is not None and right.url is not None and left.url == right.url)
    )


def _raw_fetch_from_entry(entry: _FeedEntry, source: NewsSourceConfig) -> RawArticleFetch:
    fetched_at = datetime.now(timezone.utc)
    content_hash = raw_content_hash(
        {
            "source_reference": entry.ref.source_reference,
            "raw_title": entry.raw_title,
            "raw_body": entry.raw_body,
            "raw_html": entry.raw_html,
            "summary": entry.summary,
            "published_at_raw": entry.published_at_raw,
            "author_or_channel": entry.author_or_channel,
        }
    )
    return RawArticleFetch(
        ref=entry.ref,
        source=source,
        raw_title=entry.raw_title,
        raw_body=entry.raw_body,
        raw_html=entry.raw_html,
        summary=entry.summary,
        published_at_raw=entry.published_at_raw,
        author_or_channel=entry.author_or_channel,
        fetched_at=fetched_at,
        content_hash=content_hash,
        trace_id=trace_id_for(source.source_id, content_hash, fetched_at),
    )
