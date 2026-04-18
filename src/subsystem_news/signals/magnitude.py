"""Local Ex-2 magnitude, scope, and horizon finalization."""

from __future__ import annotations

from subsystem_news.contracts.candidates import NewsFactCandidate
from subsystem_news.contracts.taxonomy import ImpactScope, TimeHorizon
from subsystem_news.signals.direction_judge import SignalJudgement


_HIGH_IMPACT_FACT_TYPES = {"accident", "litigation", "regulation_impact", "m_and_a"}
_RELIABILITY_ADJUSTMENT = {
    "A": 0.04,
    "B": 0.0,
    "C": -0.04,
}


def estimate_magnitude(
    fact: NewsFactCandidate,
    judgement: SignalJudgement,
) -> str | float:
    """Estimate a coarse Ex-2 signal magnitude from local confidence and fact type."""

    score = (
        (fact.confidence + judgement.confidence) / 2
        + _RELIABILITY_ADJUSTMENT[fact.source_reliability_tier]
    )
    score = min(1.0, max(0.0, score))

    if judgement.direction == "neutral":
        return "low"
    if score >= 0.82:
        return "high"
    if fact.fact_type in _HIGH_IMPACT_FACT_TYPES and score >= 0.70:
        return "high"
    if score >= 0.60:
        return "medium"
    return "low"


def derive_impact_scope(
    fact: NewsFactCandidate,
    judgement: SignalJudgement,
) -> ImpactScope:
    """Return the final impact scope for the signal candidate."""

    _ = fact
    return judgement.impact_scope


def derive_time_horizon(
    fact: NewsFactCandidate,
    judgement: SignalJudgement,
) -> TimeHorizon:
    """Return the final time horizon for the signal candidate."""

    _ = fact
    return judgement.time_horizon


__all__ = ["derive_impact_scope", "derive_time_horizon", "estimate_magnitude"]
