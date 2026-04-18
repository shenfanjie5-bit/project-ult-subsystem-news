"""Conflict trace generation for dedupe clusters."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.dedupe.similarity import title_similarity

_PUBLISHED_AT_CONFLICT_WINDOW = timedelta(hours=36)


class ConflictTrace(BaseModel):
    """Trace-only record for deterministic dedupe conflicts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conflict_type: Literal[
        "published_at_conflict",
        "title_divergence",
        "source_reference_drift",
    ]
    article_ids: list[str] = Field(min_length=2)
    detail: str


def detect_conflicts(members: Sequence[NewsArticleArtifact]) -> list[ConflictTrace]:
    """Detect deterministic conflicts without making a semantic ruling."""

    ordered_members = sorted(members, key=lambda artifact: artifact.article_id)
    conflicts: list[ConflictTrace] = []
    if len(ordered_members) < 2:
        return conflicts

    conflicts.extend(_published_at_conflicts(ordered_members))
    conflicts.extend(_title_conflicts(ordered_members))
    conflicts.extend(_source_reference_conflicts(ordered_members))
    return conflicts


def write_conflict_trace(
    cluster: NewsDedupeCluster,
    conflicts: Sequence[ConflictTrace],
    trace_dir: Path,
) -> Path | None:
    """Write cluster conflicts as local JSON trace state when present."""

    if not conflicts:
        return None
    if not cluster.cluster_id or "/" in cluster.cluster_id or "\\" in cluster.cluster_id:
        raise ValueError("cluster_id must be safe for conflict trace storage")
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{cluster.cluster_id}.conflicts.json"
    payload = {
        "cluster_id": cluster.cluster_id,
        "conflicts": [conflict.model_dump(mode="json") for conflict in conflicts],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _published_at_conflicts(
    members: Sequence[NewsArticleArtifact],
) -> list[ConflictTrace]:
    earliest = min(members, key=lambda artifact: artifact.published_at)
    latest = max(members, key=lambda artifact: artifact.published_at)
    if latest.published_at - earliest.published_at <= _PUBLISHED_AT_CONFLICT_WINDOW:
        return []
    return [
        ConflictTrace(
            conflict_type="published_at_conflict",
            article_ids=[earliest.article_id, latest.article_id],
            detail=(
                "published_at values differ by more than "
                f"{int(_PUBLISHED_AT_CONFLICT_WINDOW.total_seconds() // 3600)} hours"
            ),
        )
    ]


def _title_conflicts(members: Sequence[NewsArticleArtifact]) -> list[ConflictTrace]:
    conflicts: list[ConflictTrace] = []
    for left_index, left in enumerate(members):
        for right in members[left_index + 1 :]:
            if title_similarity(left, right) < 0.35:
                conflicts.append(
                    ConflictTrace(
                        conflict_type="title_divergence",
                        article_ids=[left.article_id, right.article_id],
                        detail="cluster member titles have low deterministic overlap",
                    )
                )
    return conflicts


def _source_reference_conflicts(
    members: Sequence[NewsArticleArtifact],
) -> list[ConflictTrace]:
    conflicts: list[ConflictTrace] = []
    provider_key_urls: defaultdict[str, set[str]] = defaultdict(set)
    provider_key_articles: defaultdict[str, list[str]] = defaultdict(list)
    url_provider_keys: defaultdict[str, set[str]] = defaultdict(set)
    url_articles: defaultdict[str, list[str]] = defaultdict(list)

    for artifact in members:
        provider_key = artifact.source_reference.provider_key
        url = str(artifact.source_reference.url) if artifact.source_reference.url is not None else None
        if provider_key is not None:
            provider_key_articles[provider_key].append(artifact.article_id)
            if url is not None:
                provider_key_urls[provider_key].add(url)
        if url is not None:
            url_articles[url].append(artifact.article_id)
            if provider_key is not None:
                url_provider_keys[url].add(provider_key)

    for provider_key, urls in sorted(provider_key_urls.items()):
        if len(urls) > 1:
            conflicts.append(
                ConflictTrace(
                    conflict_type="source_reference_drift",
                    article_ids=sorted(provider_key_articles[provider_key]),
                    detail=f"provider_key {provider_key} maps to multiple URLs",
                )
            )
    for url, provider_keys in sorted(url_provider_keys.items()):
        if len(provider_keys) > 1:
            conflicts.append(
                ConflictTrace(
                    conflict_type="source_reference_drift",
                    article_ids=sorted(url_articles[url]),
                    detail=f"url {url} maps to multiple provider keys",
                )
            )
    return conflicts
