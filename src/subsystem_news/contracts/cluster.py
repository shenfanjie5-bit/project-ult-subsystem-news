"""Dedupe cluster contract models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NewsDedupeCluster(BaseModel):
    """Traceable cluster of articles that report the same event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster_id: str
    representative_article_id: str
    member_article_ids: list[str] = Field(min_length=1)
    canonical_headline: str
    first_published_at: datetime
    source_count: int = Field(ge=1)
    fingerprint_family: str
    cluster_confidence: float = Field(ge=0.0, le=1.0)
