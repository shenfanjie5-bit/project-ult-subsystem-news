"""Ex-3 graph relation extraction orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import NewsFactCandidate, NewsGraphDeltaCandidate
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.entities.resolution import EntityResolutionResult
from subsystem_news.errors import ContractViolationError, EvidenceMissingError
from subsystem_news.extract.runtime_client import ReasonerRuntimeClient
from subsystem_news.extract.schema_pin import SchemaPin
from subsystem_news.graph.candidate_builder import build_graph_delta_candidate
from subsystem_news.graph.evidence_guard import validate_graph_evidence
from subsystem_news.graph.prompt import build_relation_extraction_request
from subsystem_news.graph.schema_pin import GRAPH_SCHEMA_PIN


class RelationExtractionInput(BaseModel):
    """Representative article, cluster, entity trace, and Ex-1 facts for Ex-3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article: NewsArticleArtifact
    cluster: NewsDedupeCluster
    entity_resolution: EntityResolutionResult
    facts: list[NewsFactCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_representative_article(self) -> "RelationExtractionInput":
        if self.article.article_id != self.cluster.representative_article_id:
            raise ValueError("article.article_id must match cluster.representative_article_id")

        for mention in self.entity_resolution.mentions:
            if mention.article_id != self.article.article_id:
                raise ValueError("entity_resolution mentions must match article.article_id")
        for resolved in self.entity_resolution.resolved_mentions:
            if resolved.mention.article_id != self.article.article_id:
                raise ValueError("resolved mention spans must match article.article_id")
        for fact in self.facts:
            if fact.article_id != self.article.article_id:
                raise ValueError("facts must be extracted from the representative article")
            if fact.cluster_id != self.cluster.cluster_id:
                raise ValueError("facts must carry the input cluster_id")
        return self


def extract_graph_deltas(
    article: NewsArticleArtifact,
    cluster: NewsDedupeCluster,
    entity_resolution: EntityResolutionResult,
    facts: Sequence[NewsFactCandidate],
    client: ReasonerRuntimeClient,
    *,
    schema_pin: SchemaPin = GRAPH_SCHEMA_PIN,
    min_confidence: float = 0.75,
) -> list[NewsGraphDeltaCandidate]:
    """Extract locally guarded Ex-3 graph delta candidates."""

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")

    try:
        extraction_input = RelationExtractionInput(
            article=article,
            cluster=cluster,
            entity_resolution=entity_resolution,
            facts=list(facts),
        )
    except ValidationError as exc:
        raise ContractViolationError(
            "graph extraction input violates article, cluster, entity, or fact identity"
        ) from exc

    if not extraction_input.facts:
        return []

    request = build_relation_extraction_request(
        extraction_input,
        schema_pin=schema_pin,
    )
    response = client.generate_structured(request)
    drafts = _graph_delta_drafts(response)

    candidates: list[NewsGraphDeltaCandidate] = []
    for draft in drafts:
        if not isinstance(draft, Mapping):
            raise ContractViolationError("runtime graph delta candidate must be a mapping")

        confidence = _coerce_confidence(draft.get("confidence"))
        if confidence < min_confidence:
            continue

        candidate = build_graph_delta_candidate(
            article,
            draft,
            entity_resolution,
            source_reference=article.source_reference,
        )
        if candidate is None:
            continue
        try:
            candidates.append(
                validate_graph_evidence(
                    article,
                    candidate,
                    entity_resolution=entity_resolution,
                )
            )
        except (ContractViolationError, EvidenceMissingError):
            continue

    return candidates


def _graph_delta_drafts(response: Mapping[str, object]) -> list[object]:
    if "graph_deltas" not in response:
        raise ContractViolationError("runtime response missing graph_deltas")
    raw = response["graph_deltas"]
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ContractViolationError("runtime response field graph_deltas must be a list")
    return list(raw)


def _coerce_confidence(raw_confidence: object) -> float:
    try:
        confidence = float(raw_confidence)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ContractViolationError("graph delta confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ContractViolationError("graph delta confidence must be between 0 and 1")
    return confidence


__all__ = ["RelationExtractionInput", "extract_graph_deltas"]
