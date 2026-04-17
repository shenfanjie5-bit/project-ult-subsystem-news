"""Article artifact contract models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class NewsArticleArtifact(BaseModel):
    """Local authoritative copy of a fetched and normalized news article."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str
    source_id: str
    source_reference: dict[str, Any]
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
