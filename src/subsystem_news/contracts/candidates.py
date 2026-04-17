"""Ex-1, Ex-2, and Ex-3 candidate contract models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.contracts.taxonomy import (
    DeltaAction,
    Direction,
    FactType,
    ImpactScope,
    RelationType,
    SignalType,
    TimeHorizon,
)
from subsystem_news.errors import EvidenceMissingError


class InvolvedEntity(BaseModel):
    """Entity mention plus the current resolution result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mention_text: str
    canonical_id: str | None
    resolution_status: Literal["resolved", "unresolved", "ambiguous"]
    type_hint: str

    @model_validator(mode="after")
    def validate_resolution_consistency(self) -> "InvolvedEntity":
        if self.resolution_status == "resolved":
            if self.canonical_id is None or not self.canonical_id.strip():
                raise ValueError("resolved entity requires non-empty canonical_id")
            return self

        if self.canonical_id is not None:
            raise ValueError(f"{self.resolution_status} entity requires canonical_id to be null")

        return self


class _EvidenceRequiredModel(BaseModel):
    """Shared evidence guard for Ex candidates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_spans: list[EvidenceSpan]

    @model_validator(mode="after")
    def validate_evidence_present(self) -> "_EvidenceRequiredModel":
        if not self.evidence_spans:
            raise EvidenceMissingError("candidate requires at least one evidence span")
        return self


class NewsFactCandidate(_EvidenceRequiredModel):
    """Ex-1 candidate fact extracted from a news article."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    article_id: str
    cluster_id: str | None
    source_reference: SourceReference
    fact_type: FactType
    summary: str
    involved_entities: list[InvolvedEntity]
    event_time: datetime | None
    confidence: float = Field(ge=0.0, le=1.0)
    source_reliability_tier: Literal["A", "B", "C"]
    export_contract: Literal["Ex-1"] = "Ex-1"


class NewsSignalCandidate(_EvidenceRequiredModel):
    """Ex-2 candidate signal derived from supported news evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    article_id: str
    cluster_id: str | None
    source_reference: SourceReference
    signal_type: SignalType
    direction: Direction
    magnitude: str | float
    affected_entities: list[InvolvedEntity] = Field(min_length=1)
    impact_scope: ImpactScope
    time_horizon: TimeHorizon
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    export_contract: Literal["Ex-2"] = "Ex-2"


class NewsGraphDeltaCandidate(_EvidenceRequiredModel):
    """Ex-3 candidate graph delta supported by explicit relation evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    article_id: str
    source_reference: SourceReference
    subject_entity: InvolvedEntity
    relation_type: RelationType
    object_entity: InvolvedEntity
    delta_action: DeltaAction
    valid_from: datetime | None
    confidence: float = Field(ge=0.0, le=1.0)
    requires_manual_review: bool
    export_contract: Literal["Ex-3"] = "Ex-3"
