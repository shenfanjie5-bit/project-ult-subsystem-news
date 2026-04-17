from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.errors import ContractViolationError
from subsystem_news.normalize.fingerprint_seed import content_hash
from subsystem_news.normalize.pipeline import normalize_article
from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.sources.base import RawArticleFetch


FIXTURE_ROOT = Path("src/subsystem_news/fixtures/normalize")


def load_artifact(name: str = "single_source_en.json") -> NewsArticleArtifact:
    raw = RawArticleFetch.model_validate(
        json.loads((FIXTURE_ROOT / name).read_text())
    )
    return normalize_article(raw)


def test_artifact_store_saves_and_loads_contract_model(tmp_path: Path) -> None:
    artifact = load_artifact()
    store = ArtifactStore(tmp_path)

    first_path = store.save(artifact)
    second_path = store.save(artifact)

    assert first_path == second_path
    assert first_path == store.path_for(artifact.article_id)
    assert len(list(tmp_path.glob(f"{artifact.article_id}.json"))) == 1
    assert store.exists(artifact.article_id)
    assert store.load(artifact.article_id) == artifact


def test_artifact_store_rejects_content_drift_for_existing_article_id(tmp_path: Path) -> None:
    artifact = load_artifact()
    store = ArtifactStore(tmp_path)
    store.save(artifact)
    changed_body = f"{artifact.body_text}\nCorrected copy from refetch."
    drifted_artifact = artifact.model_copy(
        update={
            "body_text": changed_body,
            "content_hash": content_hash(changed_body),
        }
    )

    with pytest.raises(ContractViolationError, match="different content_hash"):
        store.save(drifted_artifact)

    assert store.load(artifact.article_id) == artifact
    assert "Corrected copy" not in store.path_for(artifact.article_id).read_text(encoding="utf-8")


def test_artifact_store_concurrent_content_drift_does_not_replace_first_writer(
    tmp_path: Path,
) -> None:
    artifact = load_artifact("chinese_rss_summary.json")
    store = ArtifactStore(tmp_path)
    changed_body = f"{artifact.body_text}\nCorrected copy from concurrent refetch."
    drifted_artifact = artifact.model_copy(
        update={
            "body_text": changed_body,
            "content_hash": content_hash(changed_body),
        }
    )
    barrier = threading.Barrier(2)

    def save_candidate(candidate: NewsArticleArtifact) -> tuple[str, str]:
        barrier.wait()
        try:
            store.save(candidate)
        except ContractViolationError as exc:
            return "rejected", str(exc)
        return "saved", candidate.content_hash

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save_candidate, [artifact, drifted_artifact]))

    saved = [detail for status, detail in results if status == "saved"]
    rejected = [detail for status, detail in results if status == "rejected"]
    assert len(saved) == 1
    assert len(rejected) == 1
    assert "different content_hash" in rejected[0]

    stored_artifact = store.load(artifact.article_id)
    stored_metadata = store.load_metadata(artifact.article_id)
    assert stored_artifact.content_hash == saved[0]
    assert stored_metadata.content_hash == stored_artifact.content_hash
    assert stored_metadata.text_quality == "summary_only"
    assert len(list(tmp_path.glob(f"{artifact.article_id}.json"))) == 1
    assert len(list(tmp_path.glob(f"{artifact.article_id}.metadata.json"))) == 1


def test_artifact_store_persists_summary_only_metadata_sidecar(tmp_path: Path) -> None:
    artifact = load_artifact("chinese_rss_summary.json")
    store = ArtifactStore(tmp_path)

    store.save(artifact)
    loaded = store.load(artifact.article_id)
    metadata = store.load_metadata(artifact.article_id)

    assert loaded == artifact
    assert metadata.article_id == artifact.article_id
    assert metadata.content_hash == artifact.content_hash
    assert metadata.body_text_source == "summary"
    assert metadata.text_quality == "summary_only"


def test_artifact_store_load_rejects_bad_json(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    article_id = "article-bad-json"
    store.path_for(article_id).write_text("{not json", encoding="utf-8")

    with pytest.raises(ContractViolationError):
        store.load(article_id)


def test_artifact_store_load_rejects_missing_contract_fields(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    article_id = "article-missing-fields"
    store.path_for(article_id).write_text('{"article_id": "article-missing-fields"}', encoding="utf-8")

    with pytest.raises(ContractViolationError):
        store.load(article_id)


def test_artifact_store_rejects_unsafe_article_id(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ContractViolationError):
        store.path_for("../escape")
