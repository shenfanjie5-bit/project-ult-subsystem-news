from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from subsystem_news.dedupe.cluster import (
    build_cluster,
    cluster_candidates,
    exact_match,
    merge_into_cluster,
    select_representative,
)
from subsystem_news.dedupe.store import DedupeStore

from .helpers import load_pair_fixture, make_artifact


def test_exact_match_merges_on_content_hash(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    first = make_artifact(article_id="exact-a", content_hash="sha256:same-content")
    second = make_artifact(
        article_id="exact-b",
        source_id="source-b",
        provider_key="provider-b",
        url="https://source-b.example.com/exact-b",
        content_hash="sha256:same-content",
        article_fingerprint="sha256:exact-b-fp",
    )

    first_cluster = merge_into_cluster(first, store)
    second_cluster = merge_into_cluster(second, store)

    assert second_cluster.cluster_id == first_cluster.cluster_id
    assert second_cluster.cluster_confidence == 1.0
    assert second_cluster.source_count == 2
    assert exact_match(second, store) == second_cluster


def test_cluster_candidates_returns_exact_match_before_weak_match(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    first = make_artifact(article_id="exact-provider-a", provider_key="shared-provider-key")
    second = make_artifact(
        article_id="exact-provider-b",
        source_id="source-b",
        provider_key="shared-provider-key",
        url="https://source-b.example.com/exact-provider-b",
        content_hash="sha256:provider-b",
        article_fingerprint="sha256:provider-b-fp",
    )
    cluster = merge_into_cluster(first, store)

    matches = cluster_candidates(second, store)

    assert len(matches) == 1
    assert matches[0].cluster == cluster
    assert matches[0].reason == "exact"
    assert matches[0].score == 1.0


def test_exact_match_uses_normalized_url(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    first = make_artifact(
        article_id="exact-url-a",
        provider_key=None,
        url="https://News.Example.com/path/",
    )
    second = make_artifact(
        article_id="exact-url-b",
        source_id="source-b",
        provider_key=None,
        url="https://news.example.com/path",
        content_hash="sha256:exact-url-b",
        article_fingerprint="sha256:exact-url-b-fp",
    )
    cluster = merge_into_cluster(first, store)

    matches = cluster_candidates(second, store)

    assert matches[0].cluster == cluster
    assert matches[0].reason == "exact"


def test_curated_repost_pairs_merge_with_high_precision(tmp_path: Path) -> None:
    matched = 0
    pairs = load_pair_fixture("curated_repost_pairs.json")
    for index, (left, right) in enumerate(pairs):
        store = DedupeStore(tmp_path / f"pair-{index}")
        left_cluster = merge_into_cluster(left, store)
        right_cluster = merge_into_cluster(right, store)
        if right_cluster.cluster_id == left_cluster.cluster_id:
            matched += 1
        assert right_cluster.source_count == 2

    assert len(pairs) >= 20
    assert matched / len(pairs) >= 0.95


def test_near_miss_pairs_do_not_weak_merge(tmp_path: Path) -> None:
    pairs = load_pair_fixture("near_miss_pairs.json")
    for index, (left, right) in enumerate(pairs):
        store = DedupeStore(tmp_path / f"near-{index}")
        left_cluster = merge_into_cluster(left, store)

        assert cluster_candidates(right, store) == []
        assert merge_into_cluster(right, store).cluster_id != left_cluster.cluster_id


def test_select_representative_prefers_reliability_then_time_body_and_id() -> None:
    tier_b_earlier = make_artifact(
        article_id="rep-b",
        reliability_tier="B",
        published_at="2026-01-01T09:00:00Z",
    )
    tier_a_later = make_artifact(
        article_id="rep-a-later",
        reliability_tier="A",
        published_at="2026-01-01T11:00:00Z",
        content_hash="sha256:rep-a-later",
        article_fingerprint="sha256:rep-a-later-fp",
    )
    tier_a_earlier = make_artifact(
        article_id="rep-a-earlier",
        reliability_tier="A",
        published_at="2026-01-01T10:00:00Z",
        content_hash="sha256:rep-a-earlier",
        article_fingerprint="sha256:rep-a-earlier-fp",
    )

    assert select_representative([tier_b_earlier, tier_a_later, tier_a_earlier]) == tier_a_earlier


def test_select_representative_uses_longer_body_then_article_id() -> None:
    short = make_artifact(
        article_id="rep-short",
        content_hash="sha256:rep-short",
        article_fingerprint="sha256:rep-short-fp",
    )
    long = make_artifact(
        article_id="rep-long",
        body_text=f"{short.body_text} Extra confirmed context.",
        content_hash="sha256:rep-long",
        article_fingerprint="sha256:rep-long-fp",
    )
    lexical = make_artifact(
        article_id="rep-aaa",
        content_hash="sha256:rep-aaa",
        article_fingerprint="sha256:rep-aaa-fp",
    )

    assert select_representative([short, long]) == long
    assert select_representative([short, lexical]) == lexical


def test_build_cluster_counts_distinct_sources_not_members() -> None:
    first = make_artifact(article_id="member-a", source_id="same-source")
    second = make_artifact(
        article_id="member-b",
        source_id="same-source",
        provider_key="same-source-b",
        url="https://same-source.example.com/member-b",
        content_hash="sha256:member-b",
        article_fingerprint="sha256:member-b-fp",
    )
    third = make_artifact(
        article_id="member-c",
        source_id="other-source",
        provider_key="other-source-c",
        url="https://other-source.example.com/member-c",
        content_hash="sha256:member-c",
        article_fingerprint="sha256:member-c-fp",
    )

    cluster = build_cluster(
        [first, second, third],
        fingerprint_family="sha256:family",
        confidence=0.9,
    )

    assert cluster.source_count == 2
    assert cluster.member_article_ids == ["member-a", "member-b", "member-c"]


def test_merge_into_cluster_serializes_candidate_selection_after_store_lock(
    tmp_path: Path,
) -> None:
    store = DedupeStore(tmp_path)
    first = make_artifact(article_id="concurrent-a", content_hash="sha256:concurrent-event")
    second = make_artifact(
        article_id="concurrent-b",
        source_id="source-b",
        provider_key="provider-b",
        url="https://source-b.example.com/concurrent-b",
        content_hash="sha256:concurrent-event",
        article_fingerprint="sha256:concurrent-b-fp",
    )
    seeded_cluster = build_cluster(
        [first],
        fingerprint_family="sha256:concurrent-family",
        confidence=1.0,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with store.locked_merge():
            future = executor.submit(merge_into_cluster, second, store)
            time.sleep(0.05)
            assert not future.done()
            store.save_article_snapshot(first)
            store.save_cluster(seeded_cluster)
            store.save_article_snapshot(
                first.model_copy(update={"cluster_id": seeded_cluster.cluster_id})
            )
        second_cluster = future.result(timeout=5)

    assert second_cluster.cluster_id == seeded_cluster.cluster_id
    assert set(second_cluster.member_article_ids) == {first.article_id, second.article_id}
    assert store.cluster_for_article(first.article_id) == second_cluster
    assert store.cluster_for_article(second.article_id) == second_cluster
