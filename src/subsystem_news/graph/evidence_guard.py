"""High-threshold evidence guard for Ex-3 graph delta candidates."""

from __future__ import annotations

import re
from collections.abc import Sequence

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import InvolvedEntity, NewsGraphDeltaCandidate
from subsystem_news.entities.resolution import EntityResolutionResult
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.evidence import validate_evidence_spans


_ENTITY_LIKE_PHRASE_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*)+\b"
)

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

_COMMON_BRIDGE_BOUNDARY_TERMS = (
    "according to",
    "after",
    "although",
    "amid",
    "as",
    "because",
    "before",
    "but",
    "despite",
    "during",
    "following",
    "however",
    "meanwhile",
    "reported by",
    "while",
)

_BRIDGE_BOUNDARY_TERMS_BY_RELATION: dict[str, tuple[str, ...]] = {
    "acquired": _COMMON_BRIDGE_BOUNDARY_TERMS
    + ("about", "against", "alongside", "for", "from", "over", "to", "with"),
    "sanctioned_by": _COMMON_BRIDGE_BOUNDARY_TERMS
    + ("about", "against", "alongside", "for", "from", "over", "to", "with"),
    "supplier_of": _COMMON_BRIDGE_BOUNDARY_TERMS
    + ("about", "against", "alongside", "from", "over"),
    "partner_of": _COMMON_BRIDGE_BOUNDARY_TERMS
    + ("about", "against", "from", "over", "to"),
    "divested": _COMMON_BRIDGE_BOUNDARY_TERMS
    + ("about", "against", "alongside", "for", "from", "over", "with"),
}

_MAX_BRIDGE_CHARS_BY_RELATION = {
    "acquired": 80,
    "sanctioned_by": 80,
    "supplier_of": 120,
    "partner_of": 100,
    "divested": 120,
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

    if not any(
        _quote_supports_relation(
            span.quote,
            candidate,
            entity_resolution=entity_resolution,
        )
        for span in candidate.evidence_spans
    ):
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
    *,
    entity_resolution: EntityResolutionResult,
) -> bool:
    compact_quote = _compact_text(quote)
    normalized_quote = compact_quote.casefold()
    relation_type = candidate.relation_type
    subject_spans = _phrase_spans(candidate.subject_entity.mention_text, normalized_quote)
    object_spans = _phrase_spans(candidate.object_entity.mention_text, normalized_quote)
    if not subject_spans or not object_spans:
        return False

    trigger_spans = _relation_trigger_spans(normalized_quote, relation_type)
    if relation_type == "partner_of":
        return _supports_subject_trigger_object(
            compact_quote,
            normalized_quote,
            subject_spans,
            trigger_spans,
            object_spans,
            candidate=candidate,
            entity_resolution=entity_resolution,
        ) or _supports_subject_trigger_object(
            compact_quote,
            normalized_quote,
            object_spans,
            trigger_spans,
            subject_spans,
            candidate=candidate,
            entity_resolution=entity_resolution,
        )

    if relation_type == "sanctioned_by":
        return _supports_subject_trigger_object(
            compact_quote,
            normalized_quote,
            subject_spans,
            trigger_spans,
            object_spans,
            candidate=candidate,
            entity_resolution=entity_resolution,
        ) or _supports_sanctions_imposed_by_object_on_subject(
            compact_quote,
            normalized_quote,
            subject_spans,
            trigger_spans,
            object_spans,
            candidate=candidate,
            entity_resolution=entity_resolution,
        )

    return _supports_subject_trigger_object(
        compact_quote,
        normalized_quote,
        subject_spans,
        trigger_spans,
        object_spans,
        candidate=candidate,
        entity_resolution=entity_resolution,
    )


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


def _supports_subject_trigger_object(
    compact_quote: str,
    normalized_quote: str,
    subject_spans: Sequence[tuple[int, int]],
    trigger_spans: Sequence[tuple[int, int]],
    object_spans: Sequence[tuple[int, int]],
    *,
    candidate: NewsGraphDeltaCandidate,
    entity_resolution: EntityResolutionResult,
) -> bool:
    return any(
        _object_binds_to_trigger_complement(
            compact_quote,
            normalized_quote,
            trigger_end=trigger_end,
            object_start=object_start,
            candidate=candidate,
            entity_resolution=entity_resolution,
        )
        for _, subject_end in subject_spans
        for trigger_start, trigger_end in trigger_spans
        for object_start, _ in object_spans
        if subject_end <= trigger_start and trigger_end <= object_start
    )


def _supports_sanctions_imposed_by_object_on_subject(
    compact_quote: str,
    normalized_quote: str,
    subject_spans: Sequence[tuple[int, int]],
    trigger_spans: Sequence[tuple[int, int]],
    object_spans: Sequence[tuple[int, int]],
    *,
    candidate: NewsGraphDeltaCandidate,
    entity_resolution: EntityResolutionResult,
) -> bool:
    return any(
        _object_binds_to_trigger_complement(
            compact_quote,
            normalized_quote,
            trigger_end=trigger_end,
            object_start=object_start,
            candidate=candidate,
            entity_resolution=entity_resolution,
        )
        and _subject_binds_after_sanctioning_authority(
            normalized_quote,
            object_end=object_end,
            subject_start=subject_start,
        )
        for trigger_start, trigger_end in trigger_spans
        for object_start, object_end in object_spans
        for subject_start, _ in subject_spans
        if trigger_start <= object_start <= object_end <= subject_start
    )


def _object_binds_to_trigger_complement(
    compact_quote: str,
    normalized_quote: str,
    *,
    trigger_end: int,
    object_start: int,
    candidate: NewsGraphDeltaCandidate,
    entity_resolution: EntityResolutionResult,
) -> bool:
    relation_type = candidate.relation_type
    bridge = normalized_quote[trigger_end:object_start]
    if len(bridge.strip()) > _MAX_BRIDGE_CHARS_BY_RELATION.get(relation_type, 80):
        return False
    if _has_bridge_boundary(bridge, relation_type):
        return False
    if _has_intervening_known_entity(
        normalized_quote,
        start=trigger_end,
        end=object_start,
        candidate=candidate,
        entity_resolution=entity_resolution,
    ):
        return False
    if _ENTITY_LIKE_PHRASE_RE.search(compact_quote[trigger_end:object_start]):
        return False
    if relation_type == "divested" and not _contains_word(bridge, "to"):
        return False
    return True


def _subject_binds_after_sanctioning_authority(
    normalized_quote: str,
    *,
    object_end: int,
    subject_start: int,
) -> bool:
    bridge = normalized_quote[object_end:subject_start]
    return _contains_word(bridge, "on") or _contains_word(bridge, "against")


def _has_bridge_boundary(bridge: str, relation_type: str) -> bool:
    if re.search(r"[,.;:()]", bridge):
        return True
    terms = _BRIDGE_BOUNDARY_TERMS_BY_RELATION.get(
        relation_type,
        _COMMON_BRIDGE_BOUNDARY_TERMS,
    )
    return any(_contains_phrase(bridge, term) for term in terms)


def _has_intervening_known_entity(
    normalized_quote: str,
    *,
    start: int,
    end: int,
    candidate: NewsGraphDeltaCandidate,
    entity_resolution: EntityResolutionResult,
) -> bool:
    endpoint_keys = {
        _entity_key(candidate.subject_entity),
        _entity_key(candidate.object_entity),
    }
    known_entities = list(entity_resolution.entities)
    known_entities.extend(
        resolved.entity for resolved in entity_resolution.resolved_mentions
    )
    for entity in known_entities:
        if _entity_key(entity) in endpoint_keys:
            continue
        if any(
            start <= span_start and span_end <= end
            for span_start, span_end in _phrase_spans(
                entity.mention_text,
                normalized_quote,
            )
        ):
            return True
    return False


def _contains_word(value: str, word: str) -> bool:
    return (
        re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", value)
        is not None
    )


def _contains_phrase(value: str, phrase: str) -> bool:
    pattern = (
        r"(?<![A-Za-z0-9])"
        + re.escape(phrase).replace(r"\ ", r"\s+")
        + r"(?![A-Za-z0-9])"
    )
    return re.search(pattern, value) is not None


def _normalize_text(value: str) -> str:
    return _compact_text(value).casefold()


def _compact_text(value: str) -> str:
    return " ".join(value.split())


def _entity_key(entity: InvolvedEntity) -> tuple[str, str | None, str, str]:
    return (
        entity.mention_text,
        entity.canonical_id,
        entity.resolution_status,
        entity.type_hint,
    )


__all__ = ["validate_graph_evidence"]
