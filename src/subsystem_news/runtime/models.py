"""Runtime pipeline handoff and result models."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import (
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.entities.resolution import EntityResolutionResult
from subsystem_news.extract.schema_pin import SchemaPin


CandidatePayload = NewsFactCandidate | NewsSignalCandidate | NewsGraphDeltaCandidate


class PipelineConfig(BaseModel):
    """Filesystem and submit settings for one runtime ingest pass."""

    model_config = ConfigDict(extra="forbid")

    allowlist_path: Path
    artifact_root: Path
    dedupe_root: Path
    trace_root: Path
    submit_batch_size: int = Field(default=100, ge=1)
    dedupe_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    dry_run: bool = False


class PipelineArticleContext(BaseModel):
    """Single object passed between runtime stages for one discovered article."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    cluster_id: str
    source_reference: SourceReference
    artifact: NewsArticleArtifact
    representative_artifact: NewsArticleArtifact
    cluster: NewsDedupeCluster
    entity_resolution: EntityResolutionResult
    facts: list[NewsFactCandidate] = Field(default_factory=list)
    signals: list[NewsSignalCandidate] = Field(default_factory=list)
    graph_deltas: list[NewsGraphDeltaCandidate] = Field(default_factory=list)
    schema_pins: dict[str, SchemaPin] = Field(default_factory=dict)
    dedupe_metadata: dict[str, Any] = Field(default_factory=dict)
    entity_metadata: dict[str, Any] = Field(default_factory=dict)
    extract_metadata: dict[str, Any] = Field(default_factory=dict)
    signal_metadata: dict[str, Any] = Field(default_factory=dict)
    graph_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_handoff_identity(self) -> "PipelineArticleContext":
        if self.article_id != self.artifact.article_id:
            raise ValueError("article_id must match artifact.article_id")
        if self.source_reference != self.artifact.source_reference:
            raise ValueError("source_reference must match artifact.source_reference")
        if self.cluster_id != self.cluster.cluster_id:
            raise ValueError("cluster_id must match cluster.cluster_id")
        if self.representative_artifact.article_id != self.cluster.representative_article_id:
            raise ValueError("representative_artifact must match cluster representative")

        for resolved in self.entity_resolution.resolved_mentions:
            if resolved.mention.article_id != self.representative_artifact.article_id:
                raise ValueError("entity resolution must describe the representative article")
        for fact in self.facts:
            if fact.article_id != self.representative_artifact.article_id:
                raise ValueError("facts must be extracted from the representative article")
            if fact.cluster_id != self.cluster_id:
                raise ValueError("facts must carry the runtime cluster_id")
        for signal in self.signals:
            if signal.article_id != self.representative_artifact.article_id:
                raise ValueError("signals must be generated from representative facts")
            if signal.cluster_id != self.cluster_id:
                raise ValueError("signals must carry the runtime cluster_id")
        for graph_delta in self.graph_deltas:
            if graph_delta.article_id != self.representative_artifact.article_id:
                raise ValueError("graph_deltas must be generated from representative article")
            if graph_delta.source_reference != self.representative_artifact.source_reference:
                raise ValueError("graph_deltas must carry representative source_reference")
        return self


class PipelineArticleResult(BaseModel):
    """Per-article runtime outcome for trace and replay comparison."""

    model_config = ConfigDict(extra="forbid")

    article_id: str | None = None
    source_reference: SourceReference | None = None
    status: Literal["processed", "failed"]
    context: PipelineArticleContext | None = None
    candidate_count: int = Field(default=0, ge=0)
    submitted_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    submitted_candidate_keys: list[str] = Field(default_factory=list)
    skipped_candidate_keys: list[str] = Field(default_factory=list)
    error_stage: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_error_status(self) -> "PipelineArticleResult":
        if self.status == "failed" and not self.error_message:
            raise ValueError("failed article results require error_message")
        if self.status == "processed" and self.context is None:
            raise ValueError("processed article results require context")
        return self


class PipelineRunResult(BaseModel):
    """Traceable result for one end-to-end runtime ingest pass."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: datetime
    completed_at: datetime
    dry_run: bool
    discovered_count: int = Field(default=0, ge=0)
    fetched_count: int = Field(default=0, ge=0)
    submitted_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    article_results: list[PipelineArticleResult] = Field(default_factory=list)
    submitted_candidate_keys: list[str] = Field(default_factory=list)
    skipped_candidate_keys: list[str] = Field(default_factory=list)
    submit_receipts: list[dict[str, Any]] = Field(default_factory=list)
    stage_order: list[str] = Field(default_factory=list)
    trace_path: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_run_window(self) -> "PipelineRunResult":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must be greater than or equal to started_at")
        return self
