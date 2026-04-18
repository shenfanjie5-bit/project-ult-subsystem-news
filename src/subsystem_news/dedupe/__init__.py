"""Article fingerprinting, repost deduplication, and cluster management."""

from subsystem_news.dedupe.cluster import (
    ClusterMatch,
    DedupeDecision,
    build_cluster,
    cluster_candidates,
    exact_match,
    merge_into_cluster,
    select_representative,
)
from subsystem_news.dedupe.conflict import (
    ConflictTrace,
    detect_conflicts,
    write_conflict_trace,
)
from subsystem_news.dedupe.fingerprint import (
    article_fingerprint,
    normalized_terms,
    shingle_set,
)
from subsystem_news.dedupe.similarity import (
    article_similarity,
    body_similarity,
    jaccard_similarity,
    title_similarity,
)
from subsystem_news.dedupe.store import DedupeStore

__all__ = [
    "ClusterMatch",
    "ConflictTrace",
    "DedupeDecision",
    "DedupeStore",
    "article_fingerprint",
    "article_similarity",
    "body_similarity",
    "build_cluster",
    "cluster_candidates",
    "detect_conflicts",
    "exact_match",
    "jaccard_similarity",
    "merge_into_cluster",
    "normalized_terms",
    "select_representative",
    "shingle_set",
    "title_similarity",
    "write_conflict_trace",
]
