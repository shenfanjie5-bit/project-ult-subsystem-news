"""Build and de-amplify Ex-2 signal candidates."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Sequence

from pydantic import ValidationError

from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
    NewsSignalCandidate,
)
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
    """Keep the highest-confidence semantic duplicates per cluster."""

    if max_per_cluster_signal_type < 1:
        raise ValueError("max_per_cluster_signal_type must be at least 1")

    grouped: OrderedDict[tuple[object, ...], list[NewsSignalCandidate]] = OrderedDict()
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


def _aggregation_key(signal: NewsSignalCandidate) -> tuple[object, ...]:
    if signal.cluster_id is None:
        identity_scope = ("article", signal.article_id)
    else:
        identity_scope = ("cluster", signal.cluster_id)

    return (
        *identity_scope,
        signal.signal_type,
        signal.direction,
        _affected_entities_key(signal.affected_entities),
        _evidence_key(signal),
    )


def _affected_entities_key(
    affected_entities: Sequence[InvolvedEntity],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(sorted(_entity_key(entity) for entity in affected_entities))


def _entity_key(entity: InvolvedEntity) -> tuple[str, str, str]:
    type_hint = _normalize_key_text(entity.type_hint)
    if entity.canonical_id is not None:
        return ("canonical", _normalize_key_text(entity.canonical_id), type_hint)
    return (
        entity.resolution_status,
        _normalize_key_text(entity.mention_text),
        type_hint,
    )


def _evidence_key(signal: NewsSignalCandidate) -> str:
    evidence_payload = sorted(
        (span.locator, _normalize_key_text(span.quote))
        for span in signal.evidence_spans
    )
    encoded = json.dumps(evidence_payload, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_key_text(value: str) -> str:
    return " ".join(value.split()).casefold()


__all__ = [
    "aggregate_cluster_signals",
    "build_signal_candidate",
    "generate_signals",
]
