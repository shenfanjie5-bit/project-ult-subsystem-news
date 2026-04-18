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
    return (
        _contains_entity_text(normalized_quote, candidate.subject_entity.mention_text)
        and _contains_entity_text(normalized_quote, candidate.object_entity.mention_text)
        and _contains_relation_trigger(normalized_quote, candidate.relation_type)
    )


def _contains_entity_text(normalized_quote: str, mention_text: str) -> bool:
    normalized_mention = _normalize_text(mention_text)
    return bool(normalized_mention) and normalized_mention in normalized_quote


def _contains_relation_trigger(normalized_quote: str, relation_type: str) -> bool:
    triggers = _RELATION_TRIGGERS.get(relation_type)
    if triggers is None:
        raise ContractViolationError(f"unsupported graph relation_type: {relation_type}")
    return any(_phrase_in_text(trigger, normalized_quote) for trigger in triggers)


def _phrase_in_text(phrase: str, normalized_text: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    if re.search(r"[A-Za-z0-9]", normalized_phrase):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(normalized_phrase) + r"(?![A-Za-z0-9])"
        return re.search(pattern, normalized_text) is not None
    return normalized_phrase in normalized_text


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
