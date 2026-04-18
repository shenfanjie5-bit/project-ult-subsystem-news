from __future__ import annotations

from subsystem_news.signals import (
    derive_impact_scope,
    derive_time_horizon,
    estimate_magnitude,
)

from .helpers import load_fact, load_judgement


def test_estimate_magnitude_classifies_high_confidence_operating_event() -> None:
    fact = load_fact("positive_operating_event.json")
    judgement = load_judgement("positive_operating_event.json")

    assert estimate_magnitude(fact, judgement) == "high"
    assert derive_impact_scope(fact, judgement) == "company"
    assert derive_time_horizon(fact, judgement) == "medium"


def test_estimate_magnitude_classifies_negative_litigation_as_high_impact() -> None:
    fact = load_fact("negative_regulatory_litigation_event.json")
    judgement = load_judgement("negative_regulatory_litigation_event.json")

    assert estimate_magnitude(fact, judgement) == "high"
    assert derive_impact_scope(fact, judgement) == "company"
    assert derive_time_horizon(fact, judgement) == "medium"


def test_neutral_boundary_keeps_required_scope_and_horizon_but_low_magnitude() -> None:
    fact = load_fact("mixed_neutral_boundary.json")
    judgement = load_judgement("mixed_neutral_boundary.json")

    assert judgement.direction == "neutral"
    assert estimate_magnitude(fact, judgement) == "low"
    assert derive_impact_scope(fact, judgement) == "company"
    assert derive_time_horizon(fact, judgement) == "short"
