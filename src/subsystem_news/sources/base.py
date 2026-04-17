"""Shared source fetch payload models used by downstream normalization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.contracts.source_reference import SourceReference


class NewsArticleRef(BaseModel):
    """Traceable reference discovered from an approved source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    source_reference: SourceReference
    title: str | None = None
    published_at: str | datetime | None = None
    author_or_channel: str | None = None
    source_language: str | None = None

    @model_validator(mode="after")
    def validate_source_reference_matches_source_id(self) -> "NewsArticleRef":
        if self.source_reference.source_id != self.source_id:
            raise ValueError("source_reference.source_id must match source_id")
        return self


class RawArticleFetch(BaseModel):
    """Raw article payload after source policy checks and body fetch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_reference: SourceReference
    fetched_at: datetime
    license_tag: str
    reliability_tier: Literal["A", "B", "C"]
    source_id: str | None = Field(default=None, min_length=1)
    article_ref: NewsArticleRef | None = None
    title: str | None = None
    raw_body: str | None = None
    raw_html: str | None = None
    summary: str | None = None
    published_at: str | datetime | None = None
    author_or_channel: str | None = None
    source_language: str | None = None

    @model_validator(mode="before")
    @classmethod
    def fill_from_article_ref(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        article_ref = data.get("article_ref")
        if article_ref is None:
            return data

        if isinstance(article_ref, NewsArticleRef):
            ref_payload = article_ref.model_dump()
        elif isinstance(article_ref, dict):
            ref_payload = article_ref
        else:
            return data

        filled = dict(data)
        for field_name in (
            "source_id",
            "source_reference",
            "title",
            "published_at",
            "author_or_channel",
            "source_language",
        ):
            if filled.get(field_name) is None and ref_payload.get(field_name) is not None:
                filled[field_name] = ref_payload[field_name]
        return filled

    @model_validator(mode="after")
    def validate_source_reference_matches_source_id(self) -> "RawArticleFetch":
        if self.source_id is not None and self.source_reference.source_id != self.source_id:
            raise ValueError("source_reference.source_id must match source_id")
        if self.article_ref is not None and self.article_ref.source_reference != self.source_reference:
            raise ValueError("article_ref.source_reference must match source_reference")
        return self
