"""Cluster construction and merge decisions for deduped news articles."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.dedupe.conflict import (
    ConflictTrace,
    detect_conflicts,
    write_conflict_trace,
)
from subsystem_news.dedupe.fingerprint import article_fingerprint as dedupe_article_fingerprint
from subsystem_news.dedupe.identity import (
    has_exact_key_match,
    normalized_article_url,
    select_representative_member,
)
from subsystem_news.dedupe.similarity import article_similarity
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.errors import ContractViolationError


class ClusterMatch(BaseModel):
    """Deterministic match between an article and an existing cluster."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster: NewsDedupeCluster
    score: float = Field(ge=0.0, le=1.0)
    reason: Literal["exact", "weak"]
    matched_article_ids: list[str] = Field(min_length=1)


class DedupeDecision(BaseModel):
    """Full dedupe decision trace for callers that need merge metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster: NewsDedupeCluster
    created: bool
    match: ClusterMatch | None
    conflicts: list[ConflictTrace] = Field(default_factory=list)


def exact_match(
    artifact: NewsArticleArtifact,
    store: DedupeStore,
) -> NewsDedupeCluster | None:
    """Return an existing cluster when an exact deterministic key matches."""

    match = _exact_cluster_match(artifact, store)
    return None if match is None else match.cluster


def cluster_candidates(
    artifact: NewsArticleArtifact,
    store: DedupeStore,
    *,
    threshold: float = 0.82,
) -> list[ClusterMatch]:
    """Find exact and high-confidence weak cluster candidates."""

    exact = _exact_cluster_match(artifact, store)
    if exact is not None:
        return [exact]

    candidates: list[ClusterMatch] = []
    for cluster in store.list_clusters():
        member_scores: list[tuple[str, float]] = []
        for article_id in cluster.member_article_ids:
            member = store.load_article_snapshot(article_id)
            score = article_similarity(artifact, member)
            if score >= threshold:
                member_scores.append((article_id, score))
        if member_scores:
            best_score = max(score for _article_id, score in member_scores)
            candidates.append(
                ClusterMatch(
                    cluster=cluster,
                    score=best_score,
                    reason="weak",
                    matched_article_ids=sorted(
                        article_id for article_id, _score in member_scores
                    ),
                )
            )
    return sorted(
        candidates,
        key=lambda match: (
            -match.score,
            match.cluster.first_published_at,
            match.cluster.cluster_id,
        ),
    )


def select_representative(
    members: Sequence[NewsArticleArtifact],
) -> NewsArticleArtifact:
    """Select a deterministic cluster representative."""

    return select_representative_member(members)


def build_cluster(
    members: Sequence[NewsArticleArtifact],
    *,
    fingerprint_family: str,
    confidence: float,
) -> NewsDedupeCluster:
    """Build a validated cluster from already-normalized articles."""

    unique_members = _unique_members(members)
    if not unique_members:
        raise ContractViolationError("dedupe cluster requires at least one member")
    representative = select_representative(unique_members)
    member_ids = sorted(member.article_id for member in unique_members)
    return NewsDedupeCluster(
        cluster_id=_cluster_id_for(fingerprint_family, representative),
        representative_article_id=representative.article_id,
        member_article_ids=member_ids,
        canonical_headline=representative.title,
        first_published_at=min(member.published_at for member in unique_members),
        source_count=len({member.source_id for member in unique_members}),
        fingerprint_family=fingerprint_family,
        cluster_confidence=confidence,
    )


def merge_into_cluster(
    artifact: NewsArticleArtifact,
    store: DedupeStore,
    *,
    threshold: float = 0.82,
) -> NewsDedupeCluster:
    """Merge an artifact into a dedupe cluster or create a new one."""

    with store.locked_merge():
        return _merge_into_cluster_decision_locked(
            artifact,
            store,
            threshold=threshold,
        ).cluster


def merge_into_cluster_with_decision(
    artifact: NewsArticleArtifact,
    store: DedupeStore,
    *,
    threshold: float = 0.82,
) -> DedupeDecision:
    """Merge an artifact and return the runtime-facing dedupe decision trace."""

    with store.locked_merge():
        return _merge_into_cluster_decision_locked(
            artifact,
            store,
            threshold=threshold,
        )


def _merge_into_cluster_decision_locked(
    artifact: NewsArticleArtifact,
    store: DedupeStore,
    *,
    threshold: float,
) -> DedupeDecision:
    matches = cluster_candidates(artifact, store, threshold=threshold)
    match = matches[0] if matches else None
    if match is None:
        members = [artifact]
        cluster = build_cluster(
            members,
            fingerprint_family=dedupe_article_fingerprint(artifact),
            confidence=1.0,
        )
    else:
        existing_members = [
            store.load_article_snapshot(article_id)
            for article_id in match.cluster.member_article_ids
        ]
        members = _unique_members([*existing_members, artifact])
        if {member.article_id for member in members} == set(match.cluster.member_article_ids):
            return DedupeDecision(
                cluster=match.cluster,
                created=False,
                match=match,
                conflicts=[],
            )
        confidence = 1.0 if match.reason == "exact" else min(
            match.cluster.cluster_confidence,
            match.score,
        )
        rebuilt = build_cluster(
            members,
            fingerprint_family=match.cluster.fingerprint_family,
            confidence=confidence,
        )
        cluster = NewsDedupeCluster.model_validate(
            {
                **rebuilt.model_dump(),
                "cluster_id": match.cluster.cluster_id,
            }
        )

    conflicts = detect_conflicts(members)
    for member in members:
        store.save_article_snapshot(member.model_copy(update={"cluster_id": None}))
    store.save_cluster(cluster)
    for member in members:
        store.save_article_snapshot(member.model_copy(update={"cluster_id": cluster.cluster_id}))
    write_conflict_trace(cluster, conflicts, store.trace_dir)
    return DedupeDecision(
        cluster=cluster,
        created=match is None,
        match=match,
        conflicts=conflicts,
    )


def _exact_cluster_match(
    artifact: NewsArticleArtifact,
    store: DedupeStore,
) -> ClusterMatch | None:
    existing_cluster = store.cluster_for_article(artifact.article_id)
    if existing_cluster is not None:
        return ClusterMatch(
            cluster=existing_cluster,
            score=1.0,
            reason="exact",
            matched_article_ids=[artifact.article_id],
        )

    artifact_url = normalized_article_url(artifact)
    for snapshot in store.iter_article_snapshots():
        if has_exact_key_match(artifact, snapshot, left_url=artifact_url):
            cluster = store.cluster_for_article(snapshot.article_id)
            if cluster is not None:
                return ClusterMatch(
                    cluster=cluster,
                    score=1.0,
                    reason="exact",
                    matched_article_ids=[snapshot.article_id],
                )
    return None


def _unique_members(
    members: Sequence[NewsArticleArtifact],
) -> list[NewsArticleArtifact]:
    by_id: dict[str, NewsArticleArtifact] = {}
    for member in members:
        existing = by_id.get(member.article_id)
        if existing is not None:
            existing_without_cluster = existing.model_copy(update={"cluster_id": None})
            member_without_cluster = member.model_copy(update={"cluster_id": None})
            if existing_without_cluster != member_without_cluster:
                raise ContractViolationError(
                    "dedupe cluster received conflicting duplicate article_id"
                )
            if existing.cluster_id is None and member.cluster_id is not None:
                by_id[member.article_id] = member
            continue
        by_id[member.article_id] = member
    return list(by_id.values())


def _cluster_id_for(
    fingerprint_family: str,
    representative: NewsArticleArtifact,
) -> str:
    seed = "\n".join(
        [
            "dedupe-cluster:v1",
            fingerprint_family,
            representative.article_id,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"cluster-{digest[:24]}"
