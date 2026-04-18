"""Build and de-amplify Ex-2 signal candidates."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence

from pydantic import ValidationError

from subsystem_news.contracts.candidates import NewsFactCandidate, NewsSignalCandidate
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.runtime_client import ReasonerRuntimeClient
from subsystem_news.extract.schema_pin import SchemaPin
from subsystem_news.signals.direction_judge import SignalJudgement, judge_direction
from subsystem_news.signals.magnitude import (
    derive_impact_scope,
    derive_time_horizon,
    estimate_magnitude,
)
from subsystem_news.signals.promotion_rules import should_promote_fact
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN


def build_signal_candidate(
    fact: NewsFactCandidate,
    judgement: SignalJudgement,
    *,
    magnitude: str | float,
) -> NewsSignalCandidate:
    """Build and locally validate one Ex-2 signal candidate."""

    if isinstance(magnitude, bool) or (
        isinstance(magnitude, str) and not magnitude.strip()
    ):
        raise ContractViolationError("signal magnitude must be a non-empty string or float")

    payload = {
        "candidate_id": _signal_candidate_id(fact, judgement),
        "article_id": fact.article_id,
        "cluster_id": fact.cluster_id,
        "source_reference": fact.source_reference.model_dump(mode="json"),
        "signal_type": judgement.signal_type,
        "direction": judgement.direction,
        "magnitude": magnitude,
        "affected_entities": [
            entity.model_dump(mode="json") for entity in fact.involved_entities
        ],
        "impact_scope": derive_impact_scope(fact, judgement),
        "time_horizon": derive_time_horizon(fact, judgement),
        "rationale": judgement.rationale,
        "evidence_spans": [span.model_dump(mode="json") for span in fact.evidence_spans],
        "confidence": round(min(fact.confidence, judgement.confidence), 4),
        "export_contract": "Ex-2",
    }

    try:
        return NewsSignalCandidate.model_validate(payload)
    except ValidationError as exc:
        raise ContractViolationError("signal candidate violates Ex-2 contract") from exc


def aggregate_cluster_signals(
    signals: Sequence[NewsSignalCandidate],
    *,
    max_per_cluster_signal_type: int = 1,
) -> list[NewsSignalCandidate]:
    """Keep the highest-confidence signals per cluster and signal type."""

    if max_per_cluster_signal_type < 1:
        raise ValueError("max_per_cluster_signal_type must be at least 1")

    grouped: OrderedDict[
        tuple[str, str, str],
        list[NewsSignalCandidate],
    ] = OrderedDict()
    for signal in signals:
        group_key = _aggregation_key(signal)
        grouped.setdefault(group_key, []).append(signal)

    aggregated: list[NewsSignalCandidate] = []
    for grouped_signals in grouped.values():
        selected = sorted(
            grouped_signals,
            key=lambda signal: (-signal.confidence, signal.candidate_id),
        )[:max_per_cluster_signal_type]
        aggregated.extend(selected)

    return aggregated


def generate_signals(
    facts: Sequence[NewsFactCandidate],
    client: ReasonerRuntimeClient,
    *,
    schema_pin: SchemaPin = SIGNAL_SCHEMA_PIN,
    max_per_cluster_signal_type: int = 1,
    min_fact_confidence: float = 0.55,
) -> list[NewsSignalCandidate]:
    """Promote, judge, build, and cluster-de-amplify Ex-2 signal candidates."""

    signals: list[NewsSignalCandidate] = []
    for fact in facts:
        decision = should_promote_fact(fact, min_confidence=min_fact_confidence)
        if not decision.promote:
            continue

        judgement = judge_direction(fact, client, schema_pin=schema_pin)
        judgement = judgement.model_copy(
            update={"confidence": min(judgement.confidence, decision.base_confidence)}
        )
        magnitude = estimate_magnitude(fact, judgement)
        signals.append(
            build_signal_candidate(
                fact,
                judgement,
                magnitude=magnitude,
            )
        )

    return aggregate_cluster_signals(
        signals,
        max_per_cluster_signal_type=max_per_cluster_signal_type,
    )


def _signal_candidate_id(
    fact: NewsFactCandidate,
    judgement: SignalJudgement,
) -> str:
    return f"signal:{fact.candidate_id}:{judgement.signal_type}"


def _aggregation_key(signal: NewsSignalCandidate) -> tuple[str, str, str]:
    if signal.cluster_id is None:
        return ("article", signal.article_id, signal.signal_type)
    return ("cluster", signal.cluster_id, signal.signal_type)


__all__ = [
    "aggregate_cluster_signals",
    "build_signal_candidate",
    "generate_signals",
]
