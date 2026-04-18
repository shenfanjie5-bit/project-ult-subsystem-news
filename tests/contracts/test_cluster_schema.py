from __future__ import annotations

from pydantic import ValidationError
import pytest

from subsystem_news.contracts.cluster import NewsDedupeCluster


def valid_cluster_payload() -> dict[str, object]:
    return {
        "cluster_id": "cluster-a",
        "representative_article_id": "article-a",
        "member_article_ids": ["article-a", "article-b"],
        "canonical_headline": "Acme signs agreement",
        "first_published_at": "2026-01-01T10:00:00Z",
        "source_count": 2,
        "fingerprint_family": "sha256:family",
        "cluster_confidence": 0.91,
    }


def test_cluster_schema_accepts_valid_cluster() -> None:
    cluster = NewsDedupeCluster.model_validate(valid_cluster_payload())

    assert cluster.representative_article_id == "article-a"
    assert cluster.source_count == 2


def test_cluster_schema_rejects_representative_outside_members() -> None:
    payload = valid_cluster_payload()
    payload["representative_article_id"] = "article-missing"

    with pytest.raises(ValidationError, match="representative_article_id"):
        NewsDedupeCluster.model_validate(payload)


def test_cluster_schema_rejects_duplicate_member_ids() -> None:
    payload = valid_cluster_payload()
    payload["member_article_ids"] = ["article-a", "article-a"]

    with pytest.raises(ValidationError, match="member_article_ids"):
        NewsDedupeCluster.model_validate(payload)


def test_cluster_schema_rejects_source_count_above_member_count() -> None:
    payload = valid_cluster_payload()
    payload["source_count"] = 3

    with pytest.raises(ValidationError, match="source_count"):
        NewsDedupeCluster.model_validate(payload)
