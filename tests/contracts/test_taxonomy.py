from __future__ import annotations

from typing import get_args

from subsystem_news.contracts.taxonomy import (
    DeltaAction,
    Direction,
    FactType,
    ImpactScope,
    RelationType,
    SignalType,
    TimeHorizon,
)


def test_fact_type_values_are_frozen() -> None:
    assert get_args(FactType) == (
        "accident",
        "contract",
        "product",
        "regulation_impact",
        "m_and_a",
        "supply_chain",
        "litigation",
    )


def test_signal_taxonomy_values_are_frozen() -> None:
    assert get_args(SignalType) == ("sentiment", "event_impact", "sector_rotation")
    assert get_args(Direction) == ("positive", "negative", "neutral", "mixed")
    assert get_args(ImpactScope) == ("company", "sector", "supply_chain", "market_theme")
    assert get_args(TimeHorizon) == ("short", "medium", "long")


def test_graph_taxonomy_values_are_frozen() -> None:
    assert get_args(RelationType) == (
        "supplier_of",
        "acquired",
        "sanctioned_by",
        "partner_of",
        "divested",
    )
    assert get_args(DeltaAction) == ("add", "update", "deactivate")
