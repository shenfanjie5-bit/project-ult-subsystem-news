"""High-threshold evidence guard for Ex-3 graph delta candidates."""

from __future__ import annotations

import re
from collections.abc import Sequence

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import InvolvedEntity, NewsGraphDeltaCandidate
from subsystem_news.entities.resolution import EntityResolutionResult
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.evidence import validate_evidence_spans


_RELATION_TRIGGERS: dict[str, tuple[str, ...]] = {
    "supplier_of": (
        "supplier of",
        "supplies",
        "supplied",
        "supply agreement",
        "supply contract",
        "will supply",
        "to supply",
        "provides",
        "provided",
    ),
    "acquired": (
        "acquired",
        "acquires",
        "acquisition of",
        "bought",
        "purchased",
        "takeover of",
        "completed its purchase of",
    ),
    "sanctioned_by": (
        "sanctioned by",
        "sanctions imposed by",
        "blacklisted by",
        "placed on sanctions list by",
        "was sanctioned by",
        "were sanctioned by",
    ),
    "partner_of": (
        "partnered with",
        "partnership with",
        "strategic partnership",
        "joint venture with",
        "alliance with",
        "collaboration with",
    ),
    "divested": (
        "divested",
        "divestiture",
        "sold its stake",
        "sold a stake",
        "sold its unit",
        "spun off",
        "disposed of",
    ),
}


def validate_graph_evidence(
    article: NewsArticleArtifact,
    candidate: NewsGraphDeltaCandidate,
    *,
    entity_resolution: EntityResolutionResult,
) -> NewsGraphDeltaCandidate:
    """Ensure an Ex-3 candidate has resolved endpoints and explicit evidence."""

    if article.reliability_tier == "C":
        raise ContractViolationError("graph evidence requires high-reliability source")
    _require_resolved_endpoint(candidate.subject_entity, role="subject")
    _require_resolved_endpoint(candidate.object_entity, role="object")
    _require_entities_from_resolution(
        (candidate.subject_entity, candidate.object_entity),
        entity_resolution,
    )
    validate_evidence_spans(article, candidate.evidence_spans)

    if not any(_quote_supports_relation(span.quote, candidate) for span in candidate.evidence_spans):
        raise ContractViolationError(
            "graph evidence quote must include subject, object, and explicit relation trigger"
        )

    return candidate


def _require_resolved_endpoint(entity: InvolvedEntity, *, role: str) -> None:
    if entity.resolution_status != "resolved" or entity.canonical_id is None:
        raise ContractViolationError(f"graph {role} entity must be resolved with canonical_id")


def _require_entities_from_resolution(
    entities: Sequence[InvolvedEntity],
    entity_resolution: EntityResolutionResult,
) -> None:
    allowed = {_entity_key(entity) for entity in entity_resolution.entities}
    allowed.update(
        _entity_key(resolved.entity)
        for resolved in entity_resolution.resolved_mentions
    )
    for entity in entities:
        if _entity_key(entity) not in allowed:
            raise ContractViolationError(
                "graph subject and object entities must come from entity_resolution"
            )


def _quote_supports_relation(
    quote: str,
    candidate: NewsGraphDeltaCandidate,
) -> bool:
    normalized_quote = _normalize_text(quote)
    relation_type = candidate.relation_type
    subject_spans = _phrase_spans(candidate.subject_entity.mention_text, normalized_quote)
    object_spans = _phrase_spans(candidate.object_entity.mention_text, normalized_quote)
    if not subject_spans or not object_spans:
        return False

    if relation_type == "partner_of":
        return _contains_relation_trigger(normalized_quote, relation_type)

    trigger_spans = _relation_trigger_spans(normalized_quote, relation_type)
    return _has_ordered_spans(subject_spans, trigger_spans, object_spans)


def _contains_relation_trigger(normalized_quote: str, relation_type: str) -> bool:
    return bool(_relation_trigger_spans(normalized_quote, relation_type))


def _relation_trigger_spans(
    normalized_quote: str,
    relation_type: str,
) -> list[tuple[int, int]]:
    triggers = _RELATION_TRIGGERS.get(relation_type)
    if triggers is None:
        raise ContractViolationError(f"unsupported graph relation_type: {relation_type}")
    spans: list[tuple[int, int]] = []
    for trigger in triggers:
        spans.extend(_phrase_spans(trigger, normalized_quote))
    return spans


def _phrase_spans(phrase: str, normalized_text: str) -> list[tuple[int, int]]:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return []
    if re.search(r"[A-Za-z0-9]", normalized_phrase):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(normalized_phrase) + r"(?![A-Za-z0-9])"
        return [
            (match.start(), match.end())
            for match in re.finditer(pattern, normalized_text)
        ]

    spans: list[tuple[int, int]] = []
    start = normalized_text.find(normalized_phrase)
    while start >= 0:
        spans.append((start, start + len(normalized_phrase)))
        start = normalized_text.find(normalized_phrase, start + len(normalized_phrase))
    return spans


def _has_ordered_spans(
    subject_spans: Sequence[tuple[int, int]],
    trigger_spans: Sequence[tuple[int, int]],
    object_spans: Sequence[tuple[int, int]],
) -> bool:
    return any(
        subject_end <= trigger_start and trigger_end <= object_start
        for _, subject_end in subject_spans
        for trigger_start, trigger_end in trigger_spans
        for object_start, _ in object_spans
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _entity_key(entity: InvolvedEntity) -> tuple[str, str | None, str, str]:
    return (
        entity.mention_text,
        entity.canonical_id,
        entity.resolution_status,
        entity.type_hint,
    )


__all__ = ["validate_graph_evidence"]
