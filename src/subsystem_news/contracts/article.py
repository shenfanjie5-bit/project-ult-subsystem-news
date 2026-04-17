"""Article artifact contract models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from subsystem_news.contracts.source_reference import SourceReference


class NewsArticleArtifact(BaseModel):
    """Local authoritative copy of a fetched and normalized news article."""

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
    cluster_id: str | None

    @model_validator(mode="after")
    def validate_source_reference_matches_source_id(self) -> "NewsArticleArtifact":
        if self.source_reference.source_id != self.source_id:
            raise ValueError("source_reference.source_id must match source_id")
        return self
