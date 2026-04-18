"""Deterministic similarity scoring for normalized article artifacts."""

from __future__ import annotations

from typing import AbstractSet

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.dedupe.fingerprint import normalized_terms, shingle_set

_MIN_BODY_TOKENS_FOR_HIGH_CONFIDENCE = 25


def jaccard_similarity(left: AbstractSet[str], right: AbstractSet[str]) -> float:
    """Return Jaccard similarity for two sets."""

    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def title_similarity(left: NewsArticleArtifact, right: NewsArticleArtifact) -> float:
    """Score title overlap using both token and short-shingle agreement."""

    left_tokens = normalized_terms(left.title)
    right_tokens = normalized_terms(right.title)
    token_score = jaccard_similarity(set(left_tokens), set(right_tokens))
    shingle_score = jaccard_similarity(
        shingle_set(left_tokens, size=2),
        shingle_set(right_tokens, size=2),
    )
    return (0.45 * token_score) + (0.55 * shingle_score)


def body_similarity(left: NewsArticleArtifact, right: NewsArticleArtifact) -> float:
    """Score body overlap using deterministic shingle and token features."""

    left_tokens = normalized_terms(left.body_text)
    right_tokens = normalized_terms(right.body_text)
    token_score = jaccard_similarity(set(left_tokens), set(right_tokens))
    shingle_score = jaccard_similarity(
        shingle_set(left_tokens, size=5),
        shingle_set(right_tokens, size=5),
    )
    token_overlap_score = (0.85 * token_score) + (0.15 * shingle_score)
    return max(shingle_score, token_overlap_score)


def article_similarity(left: NewsArticleArtifact, right: NewsArticleArtifact) -> float:
    """Return a conservative repost similarity score in the range 0.0-1.0."""

    weighted_score = (0.15 * title_similarity(left, right)) + (
        0.85 * body_similarity(left, right)
    )
    shortest_body = min(
        len(normalized_terms(left.body_text)),
        len(normalized_terms(right.body_text)),
    )
    if shortest_body < _MIN_BODY_TOKENS_FOR_HIGH_CONFIDENCE:
        return min(weighted_score, 0.74)
    return weighted_score
