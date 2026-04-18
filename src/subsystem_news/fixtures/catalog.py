"""Regression fixture catalog and report models."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import InvolvedEntity
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.extract.schema_pin import SchemaPin
from subsystem_news.runtime.replay import ReplayDiff


FixtureCategory = Literal[
    "single_source",
    "repost_cluster",
    "ambiguous_entity",
    "graph_positive",
    "ex1_only",
    "graph_negative",
]


class FixtureArticleInput(BaseModel):
    """Raw fixture article input captured before normalization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str
    source_reference: SourceReference
    title: str
    body_text: str
    published_at: datetime
    fetched_at: datetime


class ExpectedCandidateSummary(BaseModel):
    """Compact expected Ex candidate identity for fixture validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    export_contract: Literal["Ex-1", "Ex-2", "Ex-3"]
    article_id: str
    cluster_id: str | None = None
    source_reference: SourceReference
    evidence_spans: list[EvidenceSpan] = Field(min_length=1)
    involved_entities: list[InvolvedEntity] = Field(default_factory=list)
    affected_entities: list[InvolvedEntity] = Field(default_factory=list)
    subject_entity: InvolvedEntity | None = None
    object_entity: InvolvedEntity | None = None
    direction: str | None = None
    magnitude: str | float | None = None
    requires_manual_review: bool | None = None
    schema_pin: SchemaPin | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_expected_contract_fields(self) -> "ExpectedCandidateSummary":
        if self.export_contract == "Ex-1" and not self.involved_entities:
            raise ValueError("Ex-1 expected output requires involved_entities")
        if self.export_contract == "Ex-2":
            if self.direction is None:
                raise ValueError("Ex-2 expected output requires direction")
            if self.magnitude is None or self.magnitude == "":
                raise ValueError("Ex-2 expected output requires magnitude")
            if not self.affected_entities:
                raise ValueError("Ex-2 expected output requires affected_entities")
        if self.export_contract == "Ex-3":
            if self.subject_entity is None or self.object_entity is None:
                raise ValueError("Ex-3 expected output requires subject and object entities")
            if self.requires_manual_review is not True:
                raise ValueError("Ex-3 expected output requires manual review")
        return self


class RegressionThresholds(BaseModel):
    """Minimum metric thresholds for regression acceptance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    dedupe_precision: float = Field(default=0.95, ge=0.0, le=1.0)
    unresolved_explicitness: float = Field(default=1.0, ge=0.0, le=1.0)
    ex2_contract_completeness: float = Field(default=1.0, ge=0.0, le=1.0)
    ex3_false_positive_rate: float = Field(default=0.01, ge=0.0, le=1.0)


class FixtureCase(BaseModel):
    """One curated replay fixture case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    category: FixtureCategory
    article_ids: list[str] = Field(min_length=1)
    expected_outputs: list[ExpectedCandidateSummary] = Field(default_factory=list)
    source_reference: SourceReference
    version_pins: dict[str, SchemaPin]
    baseline_path: str
    raw_inputs: list[FixtureArticleInput] = Field(default_factory=list)
    normalized_artifacts: list[NewsArticleArtifact] = Field(default_factory=list)
    expected_cluster_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_case_shape(self) -> "FixtureCase":
        if len(set(self.article_ids)) != len(self.article_ids):
            raise ValueError("article_ids must be unique within a fixture case")
        if not self.version_pins:
            raise ValueError("version_pins must not be empty")
        expected_contracts = {output.export_contract for output in self.expected_outputs}
        missing_pins = expected_contracts - set(self.version_pins)
        if missing_pins:
            missing = ", ".join(sorted(missing_pins))
            raise ValueError(f"version_pins missing contracts: {missing}")
        return self

    def resolved_baseline_path(self, suite_root: Path | None) -> Path:
        """Resolve the baseline snapshot path for this case."""

        path = Path(self.baseline_path)
        if path.is_absolute():
            return path
        if suite_root is not None:
            return suite_root / path
        return path


class FixtureSuite(BaseModel):
    """Full regression fixture suite loaded from manifest.json."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    suite_id: str
    suite_version: str
    cases: list[FixtureCase] = Field(min_length=1)
    thresholds: RegressionThresholds = Field(default_factory=RegressionThresholds)
    description: str | None = None
    manifest_path: Path | None = None
    root_path: Path | None = None

    @model_validator(mode="after")
    def validate_case_ids(self) -> "FixtureSuite":
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case_id values must be unique")
        return self


class RegressionCaseResult(BaseModel):
    """Per-case regression replay result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    category: FixtureCategory
    article_ids: list[str]
    status: Literal["passed", "failed"]
    baseline_path: str
    expected_outputs: list[ExpectedCandidateSummary] = Field(default_factory=list)
    replay_diff: ReplayDiff | None = None
    replay_error: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegressionReport(BaseModel):
    """CI-friendly regression report emitted by the fixture runner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    suite_id: str
    suite_version: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    thresholds: RegressionThresholds
    case_results: list[RegressionCaseResult] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    threshold_violations: list[str] = Field(default_factory=list)
    passed: bool = True

    @property
    def failed_case_count(self) -> int:
        return sum(1 for result in self.case_results if result.status == "failed")


__all__ = [
    "ExpectedCandidateSummary",
    "FixtureArticleInput",
    "FixtureCase",
    "FixtureCategory",
    "FixtureSuite",
    "RegressionCaseResult",
    "RegressionReport",
    "RegressionThresholds",
]
