from __future__ import annotations

from pathlib import Path

import pytest

from subsystem_news.dedupe.cluster import build_cluster, merge_into_cluster
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.errors import ContractViolationError

from .helpers import make_artifact


def test_store_saves_and_loads_article_snapshot_idempotently(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    artifact = make_artifact()

    first_path = store.save_article_snapshot(artifact)
    second_path = store.save_article_snapshot(artifact)

    assert first_path == second_path
    assert store.load_article_snapshot(artifact.article_id) == artifact
    assert list(store.iter_article_snapshots()) == [artifact]


def test_store_allows_snapshot_cluster_id_upgrade(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    artifact = make_artifact()
    clustered = artifact.model_copy(update={"cluster_id": "cluster-a"})

    store.save_article_snapshot(artifact)
    store.save_article_snapshot(clustered)

    assert store.load_article_snapshot(artifact.article_id) == clustered


def test_store_rejects_article_content_drift(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    artifact = make_artifact()
    drifted = artifact.model_copy(
        update={
            "body_text": "Different article body.",
            "content_hash": "sha256:different",
        }
    )

    store.save_article_snapshot(artifact)

    with pytest.raises(ContractViolationError, match="different content_hash"):
        store.save_article_snapshot(drifted)


def test_store_saves_and_loads_cluster_idempotently(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    artifact = make_artifact()
    cluster = build_cluster([artifact], fingerprint_family="sha256:family", confidence=1.0)

    first_path = store.save_cluster(cluster)
    second_path = store.save_cluster(cluster)

    assert first_path == second_path
    assert store.load_cluster(cluster.cluster_id) == cluster
    assert store.list_clusters() == [cluster]


def test_store_rejects_cluster_member_removal_drift(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    first = make_artifact(article_id="cluster-member-a")
    second = make_artifact(
        article_id="cluster-member-b",
        source_id="source-b",
        provider_key="provider-b",
        url="https://source-b.example.com/cluster-member-b",
        content_hash="sha256:cluster-member-b",
        article_fingerprint="sha256:cluster-member-b-fp",
    )
    cluster = build_cluster([first, second], fingerprint_family="sha256:family", confidence=1.0)
    reduced = build_cluster([first], fingerprint_family="sha256:family", confidence=1.0)
    reduced = reduced.model_copy(update={"cluster_id": cluster.cluster_id})

    store.save_cluster(cluster)

    with pytest.raises(ContractViolationError, match="remove members"):
        store.save_cluster(reduced)


def test_cluster_for_article_roundtrips_after_merge(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    artifact = make_artifact()

    cluster = merge_into_cluster(artifact, store)
    reloaded_store = DedupeStore(tmp_path)

    assert reloaded_store.cluster_for_article(artifact.article_id) == cluster
    assert reloaded_store.load_article_snapshot(artifact.article_id).cluster_id == cluster.cluster_id


def test_store_rejects_bad_json_on_load(tmp_path: Path) -> None:
    store = DedupeStore(tmp_path)
    path = tmp_path / "articles" / "bad-json.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ContractViolationError):
        store.load_article_snapshot("bad-json")
