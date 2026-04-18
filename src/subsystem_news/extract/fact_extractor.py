"""Ex-1 fact extraction orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import InvolvedEntity, NewsFactCandidate
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.entities.resolution import EntityResolutionResult
from subsystem_news.errors import ContractViolationError, EvidenceMissingError
from subsystem_news.extract.evidence import coerce_evidence_spans
from subsystem_news.extract.prompt import build_fact_extraction_request
from subsystem_news.extract.runtime_client import ReasonerRuntimeClient
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN, SchemaPin


class FactExtractionInput(BaseModel):
    """Representative article, dedupe cluster, and entity trace for Ex-1 extraction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article: NewsArticleArtifact
    cluster: NewsDedupeCluster
    entity_resolution: EntityResolutionResult

    @model_validator(mode="after")
    def validate_representative_article(self) -> "FactExtractionInput":
        if self.article.article_id != self.cluster.representative_article_id:
            raise ValueError("article.article_id must match cluster.representative_article_id")

        for mention in self.entity_resolution.mentions:
            if mention.article_id != self.article.article_id:
                raise ValueError("entity_resolution mentions must match article.article_id")
        for resolved in self.entity_resolution.resolved_mentions:
            if resolved.mention.article_id != self.article.article_id:
                raise ValueError("resolved mention spans must match article.article_id")
        return self


def extract_facts(
    article: NewsArticleArtifact,
    cluster: NewsDedupeCluster,
    entity_resolution: EntityResolutionResult,
    client: ReasonerRuntimeClient,
    *,
    schema_pin: SchemaPin = FACT_SCHEMA_PIN,
    min_confidence: float = 0.45,
) -> list[NewsFactCandidate]:
    """Extract locally validated Ex-1 fact candidates from a representative article."""

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")

    try:
        extraction_input = FactExtractionInput(
            article=article,
            cluster=cluster,
            entity_resolution=entity_resolution,
        )
    except ValidationError as exc:
        raise ContractViolationError(
            "fact extraction input violates article, cluster, or entity identity"
        ) from exc

    if not entity_resolution.entities:
        return []

    request = build_fact_extraction_request(extraction_input, schema_pin=schema_pin)
    response = client.generate_structured(request)
    drafts = _candidate_drafts(response)
    allowed_entities = _allowed_entity_keys(entity_resolution)
    has_resolved_entity = any(
        entity.resolution_status == "resolved" for entity in entity_resolution.entities
    )

    candidates: list[NewsFactCandidate] = []
    for draft in drafts:
        if not isinstance(draft, Mapping):
            raise ContractViolationError("runtime fact candidate must be a mapping")

        confidence = _coerce_confidence(draft.get("confidence"))
        if confidence < min_confidence:
            continue
        if not has_resolved_entity and confidence >= 0.45:
            continue

        raw_spans = draft.get("evidence_spans")
        if not isinstance(raw_spans, Sequence) or isinstance(raw_spans, str | bytes):
            raise EvidenceMissingError("fact candidate requires evidence_spans")
        evidence_spans = coerce_evidence_spans(article, raw_spans)

        candidate_payload = dict(draft)
        candidate_payload.setdefault("event_time", None)
        candidate_payload.update(
            {
                "article_id": article.article_id,
                "cluster_id": cluster.cluster_id,
                "source_reference": article.source_reference.model_dump(mode="json"),
                "source_reliability_tier": article.reliability_tier,
                "export_contract": "Ex-1",
                "evidence_spans": [
                    span.model_dump(mode="json") for span in evidence_spans
                ],
            }
        )

        try:
            candidate = NewsFactCandidate.model_validate(candidate_payload)
        except EvidenceMissingError:
            raise
        except ValidationError as exc:
            raise ContractViolationError("runtime fact candidate violates Ex-1 contract") from exc

        _validate_involved_entities(candidate.involved_entities, allowed_entities)
        candidates.append(candidate)

    return candidates


def _candidate_drafts(response: Mapping[str, object]) -> list[object]:
    for key in ("facts", "fact_candidates", "candidates"):
        if key not in response:
            continue
        raw = response[key]
        if raw is None:
            return []
        if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
            raise ContractViolationError(f"runtime response field {key} must be a list")
        return list(raw)
    return []


def _coerce_confidence(raw_confidence: object) -> float:
    try:
        confidence = float(raw_confidence)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ContractViolationError("fact candidate confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ContractViolationError("fact candidate confidence must be between 0 and 1")
    return confidence


def _allowed_entity_keys(entity_resolution: EntityResolutionResult) -> set[tuple[Any, ...]]:
    return {
        _entity_key(entity)
        for entity in [
            *entity_resolution.entities,
            *(resolved.entity for resolved in entity_resolution.resolved_mentions),
        ]
    }


def _validate_involved_entities(
    involved_entities: Sequence[InvolvedEntity],
    allowed_entities: set[tuple[Any, ...]],
) -> None:
    if not involved_entities:
        raise ContractViolationError("fact candidate requires at least one involved entity")

    for entity in involved_entities:
        if _entity_key(entity) not in allowed_entities:
            raise ContractViolationError(
                "fact candidate involved_entities must come from entity_resolution"
            )


def _entity_key(entity: InvolvedEntity) -> tuple[str, str | None, str, str]:
    return (
        entity.mention_text,
        entity.canonical_id,
        entity.resolution_status,
        entity.type_hint,
    )
