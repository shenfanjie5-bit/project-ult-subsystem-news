"""Frozen local contracts for subsystem-news artifacts and candidates."""

from __future__ import annotations

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.sources import NewsSourceConfig, load_allowlist
from subsystem_news.contracts.taxonomy import (
    DeltaAction,
    Direction,
    FactType,
    ImpactScope,
    RelationType,
    SignalType,
    TimeHorizon,
)

__all__ = [
    "DeltaAction",
    "Direction",
    "EvidenceSpan",
    "FactType",
    "ImpactScope",
    "InvolvedEntity",
    "NewsArticleArtifact",
    "NewsDedupeCluster",
    "NewsFactCandidate",
    "NewsGraphDeltaCandidate",
    "NewsSignalCandidate",
    "NewsSourceConfig",
    "RelationType",
    "SignalType",
    "TimeHorizon",
    "load_allowlist",
]
