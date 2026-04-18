"""Local rules for promoting Ex-1 facts into Ex-2 signal candidates."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from subsystem_news.contracts.candidates import NewsFactCandidate
from subsystem_news.contracts.taxonomy import SignalType


_FACT_SIGNAL_TYPES: dict[str, SignalType] = {
    "accident": "event_impact",
    "contract": "event_impact",
    "product": "event_impact",
    "regulation_impact": "event_impact",
    "m_and_a": "event_impact",
    "supply_chain": "event_impact",
    "litigation": "event_impact",
}

_RELIABILITY_ADJUSTMENT = {
    "A": 0.04,
    "B": 0.0,
    "C": -0.05,
}

_FACT_TYPE_ADJUSTMENT = {
    "accident": 0.02,
    "contract": 0.01,
    "product": 0.0,
    "regulation_impact": 0.03,
    "m_and_a": 0.03,
    "supply_chain": 0.02,
    "litigation": 0.03,
}


class PromotionDecision(BaseModel):
    """Decision record for fact-to-signal promotion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promote: bool
    signal_type: SignalType | None
    reason: str = Field(min_length=1)
    base_confidence: float = Field(ge=0.0, le=1.0)


def should_promote_fact(
    fact: NewsFactCandidate,
    *,
    min_confidence: float = 0.55,
) -> PromotionDecision:
    """Return whether a locally validated Ex-1 fact should become an Ex-2 signal."""

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0.0 and 1.0")

    signal_type = _FACT_SIGNAL_TYPES.get(fact.fact_type)
    base_confidence = _base_confidence(fact)

    if fact.confidence < min_confidence:
        return PromotionDecision(
            promote=False,
            signal_type=None,
            reason="fact confidence is below the promotion threshold",
            base_confidence=base_confidence,
        )

    if not fact.evidence_spans:
        return PromotionDecision(
            promote=False,
            signal_type=None,
            reason="fact has no local evidence spans",
            base_confidence=base_confidence,
        )

    if not fact.involved_entities:
        return PromotionDecision(
            promote=False,
            signal_type=None,
            reason="fact has no affected entity candidates",
            base_confidence=base_confidence,
        )

    if all(entity.resolution_status == "unresolved" for entity in fact.involved_entities):
        return PromotionDecision(
            promote=False,
            signal_type=None,
            reason="all involved entities are unresolved",
            base_confidence=base_confidence,
        )

    if signal_type is None:
        return PromotionDecision(
            promote=False,
            signal_type=None,
            reason=f"fact_type {fact.fact_type!r} is not promotable to Ex-2",
            base_confidence=base_confidence,
        )

    if base_confidence < min_confidence:
        return PromotionDecision(
            promote=False,
            signal_type=None,
            reason="source reliability adjusted confidence is below the promotion threshold",
            base_confidence=base_confidence,
        )

    return PromotionDecision(
        promote=True,
        signal_type=signal_type,
        reason="fact has enough confidence, evidence, and entity resolution for Ex-2",
        base_confidence=base_confidence,
    )


def _base_confidence(fact: NewsFactCandidate) -> float:
    entity_adjustment = 0.03 if any(
        entity.resolution_status == "resolved" for entity in fact.involved_entities
    ) else -0.03
    raw_confidence = (
        fact.confidence
        + _RELIABILITY_ADJUSTMENT[fact.source_reliability_tier]
        + _FACT_TYPE_ADJUSTMENT.get(fact.fact_type, 0.0)
        + entity_adjustment
    )
    return round(min(1.0, max(0.0, raw_confidence)), 4)


__all__ = ["PromotionDecision", "should_promote_fact"]
