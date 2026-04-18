"""Build locally traceable Ex-3 graph delta candidates from runtime drafts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import get_args

from pydantic import ValidationError

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import InvolvedEntity, NewsGraphDeltaCandidate
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.contracts.taxonomy import DeltaAction, RelationType
from subsystem_news.entities.resolution import EntityResolutionResult


_ALLOWED_RELATION_TYPES = frozenset(get_args(RelationType))
_ALLOWED_DELTA_ACTIONS = frozenset(get_args(DeltaAction))


def build_graph_delta_candidate(
    article: NewsArticleArtifact,
    raw: Mapping[str, object],
    entity_resolution: EntityResolutionResult,
    *,
    source_reference: SourceReference,
) -> NewsGraphDeltaCandidate | None:
    """Build one Ex-3 candidate, returning None for unsupported raw drafts."""

    relation_type = raw.get("relation_type")
    delta_action = raw.get("delta_action")
    if relation_type not in _ALLOWED_RELATION_TYPES:
        return None
    if delta_action not in _ALLOWED_DELTA_ACTIONS:
        return None

    subject = _coerce_allowed_entity(raw.get("subject_entity"), entity_resolution)
    object_entity = _coerce_allowed_entity(raw.get("object_entity"), entity_resolution)
    if subject is None or object_entity is None:
        return None

    evidence_spans = _coerce_evidence_span_payloads(raw.get("evidence_spans"))
    if evidence_spans is None:
        return None

    payload = {
        "candidate_id": _candidate_id(
            article=article,
            subject=subject,
            relation_type=str(relation_type),
            object_entity=object_entity,
            delta_action=str(delta_action),
            evidence_spans=evidence_spans,
        ),
        "article_id": article.article_id,
        "source_reference": source_reference.model_dump(mode="json"),
        "subject_entity": subject.model_dump(mode="json"),
        "relation_type": relation_type,
        "object_entity": object_entity.model_dump(mode="json"),
        "delta_action": delta_action,
        "valid_from": raw.get("valid_from", None),
        "confidence": raw.get("confidence"),
        "requires_manual_review": True,
        "export_contract": "Ex-3",
        "evidence_spans": evidence_spans,
    }

    try:
        return NewsGraphDeltaCandidate.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        return None


def _coerce_allowed_entity(
    raw_entity: object,
    entity_resolution: EntityResolutionResult,
) -> InvolvedEntity | None:
    if not isinstance(raw_entity, Mapping):
        return None
    try:
        entity = InvolvedEntity.model_validate(raw_entity)
    except (ValidationError, ValueError, TypeError):
        return None

    allowed = {_entity_key(known) for known in entity_resolution.entities}
    allowed.update(
        _entity_key(resolved.entity)
        for resolved in entity_resolution.resolved_mentions
    )
    if _entity_key(entity) not in allowed:
        return None
    return entity


def _coerce_evidence_span_payloads(raw_spans: object) -> list[dict[str, object]] | None:
    if not isinstance(raw_spans, list):
        return None
    payloads: list[dict[str, object]] = []
    for raw_span in raw_spans:
        if not isinstance(raw_span, Mapping):
            return None
        try:
            payloads.append(
                EvidenceSpan.model_validate(raw_span).model_dump(mode="json")
            )
        except (ValidationError, ValueError, TypeError):
            return None
    return payloads


def _candidate_id(
    *,
    article: NewsArticleArtifact,
    subject: InvolvedEntity,
    relation_type: str,
    object_entity: InvolvedEntity,
    delta_action: str,
    evidence_spans: list[dict[str, object]],
) -> str:
    payload = {
        "version": "news-graph-delta-candidate-id.v1",
        "article_id": article.article_id,
        "subject": _endpoint_identity(subject),
        "relation_type": relation_type,
        "object": _endpoint_identity(object_entity),
        "delta_action": delta_action,
        "evidence_spans": evidence_spans,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"graph:{digest[:32]}"


def _endpoint_identity(entity: InvolvedEntity) -> tuple[str, str | None, str, str]:
    return (
        entity.mention_text,
        entity.canonical_id,
        entity.resolution_status,
        entity.type_hint,
    )


def _entity_key(entity: InvolvedEntity) -> tuple[str, str | None, str, str]:
    return _endpoint_identity(entity)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {value!r}")


__all__ = ["build_graph_delta_candidate"]
