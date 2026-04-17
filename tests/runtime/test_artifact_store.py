from __future__ import annotations

import json
from pathlib import Path

import pytest

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.errors import ContractViolationError
from subsystem_news.normalize.pipeline import normalize_article
from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.sources.base import RawArticleFetch


FIXTURE_ROOT = Path("src/subsystem_news/fixtures/normalize")


def load_artifact() -> NewsArticleArtifact:
    raw = RawArticleFetch.model_validate(
        json.loads((FIXTURE_ROOT / "single_source_en.json").read_text())
    )
    return normalize_article(raw)


def test_artifact_store_saves_and_loads_contract_model(tmp_path: Path) -> None:
    artifact = load_artifact()
    store = ArtifactStore(tmp_path)

    first_path = store.save(artifact)
    second_path = store.save(artifact)

    assert first_path == second_path
    assert first_path == store.path_for(artifact.article_id)
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert store.exists(artifact.article_id)
    assert store.load(artifact.article_id) == artifact


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
