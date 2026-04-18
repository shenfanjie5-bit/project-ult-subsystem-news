from __future__ import annotations

from subsystem_news.dedupe.similarity import (
    article_similarity,
    body_similarity,
    jaccard_similarity,
    title_similarity,
)

from .helpers import load_pair_fixture, make_artifact


def test_jaccard_similarity_scores_set_overlap() -> None:
    assert jaccard_similarity({"a", "b"}, {"b", "c"}) == 1 / 3
    assert jaccard_similarity(set(), {"b"}) == 0.0


def test_title_and_body_similarity_are_deterministic() -> None:
    left, right = load_pair_fixture("curated_repost_pairs.json")[0]

    assert title_similarity(left, right) > 0.35
    assert body_similarity(left, right) > 0.90
    assert article_similarity(left, right) >= 0.82


def test_near_miss_fixture_scores_below_merge_threshold() -> None:
    for left, right in load_pair_fixture("near_miss_pairs.json"):
        assert article_similarity(left, right) < 0.82


def test_short_summary_like_articles_cannot_score_as_high_confidence() -> None:
    left = make_artifact(
        article_id="short-a",
        body_text="Acme signed a contract.",
        content_hash="sha256:short-a",
        article_fingerprint="sha256:short-a-fp",
    )
    right = make_artifact(
        article_id="short-b",
        source_id="source-b",
        provider_key="provider-b",
        url="https://source-b.example.com/short-b",
        body_text="Acme signed a contract.",
        content_hash="sha256:short-b",
        article_fingerprint="sha256:short-b-fp",
    )

    assert article_similarity(left, right) <= 0.74
