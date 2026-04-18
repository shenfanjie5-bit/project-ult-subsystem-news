from __future__ import annotations

import pytest

from subsystem_news.signals import PromotionDecision, should_promote_fact

from .helpers import clone_fact, load_fact


@pytest.mark.parametrize(
    "fact_type",
    ["contract", "regulation_impact", "litigation", "supply_chain"],
)
def test_high_confidence_supported_facts_promote_to_event_impact(fact_type: str) -> None:
    fact = clone_fact(
        load_fact("positive_operating_event.json"),
        fact_type=fact_type,
        confidence=0.82,
        source_reliability_tier="A",
    )

    decision = should_promote_fact(fact)

    assert isinstance(decision, PromotionDecision)
    assert decision.promote is True
    assert decision.signal_type == "event_impact"
    assert decision.base_confidence >= fact.confidence


def test_low_confidence_fact_does_not_promote() -> None:
    fact = clone_fact(load_fact("positive_operating_event.json"), confidence=0.42)

    decision = should_promote_fact(fact)

    assert decision.promote is False
    assert decision.signal_type is None
    assert "confidence" in decision.reason


def test_fact_without_evidence_does_not_promote() -> None:
    fact = load_fact("positive_operating_event.json").model_copy(
        update={"evidence_spans": []}
    )

    decision = should_promote_fact(fact)

    assert decision.promote is False
    assert "evidence" in decision.reason


def test_fact_without_affected_entities_does_not_promote() -> None:
    fact = clone_fact(load_fact("positive_operating_event.json"), involved_entities=[])

    decision = should_promote_fact(fact)

    assert decision.promote is False
    assert "entity" in decision.reason


def test_all_unresolved_ex1_only_boundary_does_not_promote() -> None:
    fact = load_fact("ex1_only_boundary.json")

    decision = should_promote_fact(fact)

    assert decision.promote is False
    assert decision.signal_type is None
    assert "unresolved" in decision.reason
