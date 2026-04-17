"""Frozen taxonomy literals for news candidate contracts."""

from __future__ import annotations

from typing import Literal


FactType = Literal[
    "accident",
    "contract",
    "product",
    "regulation_impact",
    "m_and_a",
    "supply_chain",
    "litigation",
]
SignalType = Literal["sentiment", "event_impact", "sector_rotation"]
Direction = Literal["positive", "negative", "neutral", "mixed"]
ImpactScope = Literal["company", "sector", "supply_chain", "market_theme"]
TimeHorizon = Literal["short", "medium", "long"]
RelationType = Literal[
    "supplier_of",
    "acquired",
    "sanctioned_by",
    "partner_of",
    "divested",
]
DeltaAction = Literal["add", "update", "deactivate"]
