"""Dedupe cluster contract models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def validate_cluster_integrity(self) -> "NewsDedupeCluster":
        """Validate local cluster membership invariants.

        ``source_count`` is the number of distinct article ``source_id`` values
        computed by the dedupe builder. The contract can only enforce the upper
        bound because it stores article ids, not source ids.
        """

        if self.representative_article_id not in self.member_article_ids:
            raise ValueError("representative_article_id must be a cluster member")
        if len(set(self.member_article_ids)) != len(self.member_article_ids):
            raise ValueError("member_article_ids must be unique")
        if self.source_count > len(self.member_article_ids):
            raise ValueError("source_count cannot exceed member_article_ids length")
        return self
