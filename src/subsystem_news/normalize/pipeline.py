"""Runtime article normalization pipeline."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.errors import ContractViolationError
from subsystem_news.normalize.fingerprint_seed import content_hash, fingerprint_seed
from subsystem_news.normalize.html_strip import strip_boilerplate
from subsystem_news.normalize.text_clean import clean_text, detect_language, normalize_title
from subsystem_news.normalize.time_parse import parse_published_at
from subsystem_news.sources.base import RawArticleFetch


class ParsedNewsArticle(BaseModel):
    """Normalized article data before artifact contract validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str
    source_id: str
    source_reference: SourceReference
    title: str
    body_text: str
    published_at: datetime
    fetched_at: datetime
    language: str
    author_or_channel: str
    content_hash: str
    article_fingerprint: str
    license_tag: str
    reliability_tier: Literal["A", "B", "C"]
    cluster_id: str | None = None
    body_text_source: Literal["raw_body", "raw_html", "summary"] = "raw_body"
    text_quality: Literal["full_text", "summary_only"] = "full_text"


def _clean_optional(value: str | None) -> str:
    if value is None:
        return ""
    return clean_text(value)


def _select_body_with_source(
    raw: RawArticleFetch,
) -> tuple[str, Literal["raw_body", "raw_html", "summary"]]:
    raw_body = _clean_optional(raw.raw_body)
    if raw_body:
        return raw_body, "raw_body"

    if raw.raw_html is not None:
        html_body = strip_boilerplate(raw.raw_html)
        if html_body:
            return html_body, "raw_html"

    summary = _clean_optional(raw.summary)
    if summary:
        return summary, "summary"

    raise ContractViolationError("raw article has no body text to normalize")


def select_body_text(raw: RawArticleFetch) -> str:
    """Choose body text by native body, lightweight HTML, then summary fallback."""

    body_text, _body_source = _select_body_with_source(raw)
    return body_text


def article_id_for(source_reference: SourceReference) -> str:
    """Build a deterministic local article id from source id and external locator."""

    if source_reference.url is not None:
        locator = f"url:{source_reference.url}"
    elif source_reference.provider_key is not None:
        locator = f"provider_key:{source_reference.provider_key}"
    else:
        raise ContractViolationError("source_reference requires url or provider_key")

    digest = hashlib.sha256(f"{source_reference.source_id}\n{locator}".encode("utf-8")).hexdigest()
    return f"article-{digest[:24]}"


def parse_article(raw: RawArticleFetch) -> ParsedNewsArticle:
    """Normalize a raw source fetch into a parsed runtime article object."""

    source_reference = raw.source_reference
    body_text, body_source = _select_body_with_source(raw)
    title = normalize_title(raw.title)
    fetched_at = parse_published_at(raw.fetched_at, fetched_at=raw.fetched_at)
    published_at = parse_published_at(raw.published_at, fetched_at=fetched_at)
    language = detect_language(title, body_text, raw.source_language)

    return ParsedNewsArticle(
        article_id=article_id_for(source_reference),
        source_id=source_reference.source_id,
        source_reference=source_reference,
        title=title,
        body_text=body_text,
        published_at=published_at,
        fetched_at=fetched_at,
        language=language,
        author_or_channel=_clean_optional(raw.author_or_channel),
        content_hash=content_hash(body_text),
        article_fingerprint=fingerprint_seed(title, body_text),
        license_tag=clean_text(raw.license_tag),
        reliability_tier=raw.reliability_tier,
        cluster_id=None,
        body_text_source=body_source,
        text_quality="summary_only" if body_source == "summary" else "full_text",
    )


def to_artifact(parsed: ParsedNewsArticle) -> NewsArticleArtifact:
    """Validate parsed article data against the frozen artifact contract."""

    return NewsArticleArtifact.model_validate(
        parsed.model_dump(
            include={
                "article_id",
                "source_id",
                "source_reference",
                "title",
                "body_text",
                "published_at",
                "fetched_at",
                "language",
                "author_or_channel",
                "content_hash",
                "article_fingerprint",
                "license_tag",
                "reliability_tier",
                "cluster_id",
            }
        )
    )


def normalize_article(raw: RawArticleFetch) -> NewsArticleArtifact:
    """Normalize and validate a raw article fetch as a local artifact."""

    return to_artifact(parse_article(raw))
