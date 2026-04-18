from __future__ import annotations

import json
from pathlib import Path

from subsystem_news.contracts.article import NewsArticleArtifact

FIXTURE_ROOT = Path("src/subsystem_news/fixtures/dedupe/repost_pairs")


def make_artifact(
    article_id: str = "article-a",
    *,
    source_id: str = "source-a",
    provider_key: str | None = "provider-a",
    url: str | None = "https://source-a.example.com/article-a",
    title: str = "Acme signs renewable equipment agreement",
    body_text: str = (
        "Acme Corp said it signed a three year renewable equipment supply agreement "
        "with Horizon Energy in Texas. Executives said deliveries begin in May and "
        "the agreement does not change prior annual guidance."
    ),
    published_at: str = "2026-01-01T10:00:00Z",
    fetched_at: str = "2026-01-01T10:05:00Z",
    content_hash: str = "sha256:artifact-a",
    article_fingerprint: str = "sha256:artifact-a-fp",
    reliability_tier: str = "A",
    cluster_id: str | None = None,
) -> NewsArticleArtifact:
    return NewsArticleArtifact.model_validate(
        {
            "article_id": article_id,
            "source_id": source_id,
            "source_reference": {
                "source_id": source_id,
                "url": url,
                "provider_key": provider_key,
                "original_locator": {
                    "locator_type": "fixture",
                    "locator_value": provider_key or url,
                },
            },
            "title": title,
            "body_text": body_text,
            "published_at": published_at,
            "fetched_at": fetched_at,
            "language": "en",
            "author_or_channel": "Fixture Desk",
            "content_hash": content_hash,
            "article_fingerprint": article_fingerprint,
            "license_tag": "fixture-license",
            "reliability_tier": reliability_tier,
            "cluster_id": cluster_id,
        }
    )


def load_pair_fixture(name: str) -> list[tuple[NewsArticleArtifact, NewsArticleArtifact]]:
    payload = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    return [
        (
            NewsArticleArtifact.model_validate(pair[0]),
            NewsArticleArtifact.model_validate(pair[1]),
        )
        for pair in payload
    ]


def load_group_fixture(name: str) -> list[NewsArticleArtifact]:
    payload = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    return [NewsArticleArtifact.model_validate(item) for item in payload]
