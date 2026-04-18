"""Shared identity helpers for dedupe cluster and store validation."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.errors import ContractViolationError


def normalized_article_url(artifact: NewsArticleArtifact) -> str | None:
    """Return a stable URL key for exact article identity checks."""

    if artifact.source_reference.url is None:
        return None
    parsed = urlsplit(str(artifact.source_reference.url))
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


def has_exact_key_match(
    left: NewsArticleArtifact,
    right: NewsArticleArtifact,
    *,
    left_url: str | None = None,
    provider_key_globally_unique: bool = False,
) -> bool:
    """Return whether two article snapshots share an exact dedupe identity key."""

    left_provider_key = left.source_reference.provider_key
    right_provider_key = right.source_reference.provider_key
    if (
        left_provider_key is not None
        and right_provider_key is not None
        and left_provider_key == right_provider_key
        and (
            provider_key_globally_unique
            or left.source_reference.source_id == right.source_reference.source_id
        )
    ):
        return True

    normalized_left_url = (
        normalized_article_url(left) if left_url is None else left_url
    )
    normalized_right_url = normalized_article_url(right)
    if (
        normalized_left_url is not None
        and normalized_right_url is not None
        and normalized_left_url == normalized_right_url
    ):
        return True
    if left.content_hash == right.content_hash:
        return True
    return left.article_fingerprint == right.article_fingerprint


def select_representative_member(
    members: Sequence[NewsArticleArtifact],
) -> NewsArticleArtifact:
    """Select a deterministic representative for a dedupe cluster."""

    if not members:
        raise ContractViolationError("dedupe cluster requires at least one member")
    reliability_rank = {"A": 0, "B": 1, "C": 2}
    return sorted(
        members,
        key=lambda artifact: (
            reliability_rank[artifact.reliability_tier],
            artifact.published_at,
            -len(artifact.body_text),
            artifact.article_id,
        ),
    )[0]
