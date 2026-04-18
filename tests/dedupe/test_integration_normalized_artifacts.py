from __future__ import annotations

from pathlib import Path
from typing import Mapping

from subsystem_news.contracts import NewsSourceConfig, load_allowlist
from subsystem_news.dedupe.store import DedupeStore
from subsystem_news.dedupe.cluster import merge_into_cluster
from subsystem_news.normalize.pipeline import normalize_article
from subsystem_news.runtime.artifact_store import ArtifactStore
from subsystem_news.sources import HttpResponse, discover_articles, fetch_article_body

FIXTURE_ROOT = Path("src/subsystem_news/fixtures")
SOURCE_FIXTURE_ROOT = FIXTURE_ROOT / "sources"


class StaticTransport:
    def __init__(self, responses: Mapping[str, str]) -> None:
        self._responses = responses

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        del headers
        return HttpResponse(url=url, status_code=200, text=self._responses[url], headers={})


def load_configs() -> list[NewsSourceConfig]:
    return load_allowlist(FIXTURE_ROOT / "approved_sources.valid.sample.json")


def config_by_id(source_id: str) -> NewsSourceConfig:
    for config in load_configs():
        if config.source_id == source_id:
            return config
    raise AssertionError(source_id)


def transport() -> StaticTransport:
    return StaticTransport(
        {
            "https://site.example.com/markets/plant-update": (
                SOURCE_FIXTURE_ROOT / "site_page.html"
            ).read_text(encoding="utf-8"),
        }
    )


def test_source_normalize_artifact_store_to_dedupe_store_chain(tmp_path: Path) -> None:
    configs = [config_by_id("site-html")]
    ref = discover_articles(configs, transport=transport())[0]
    raw = fetch_article_body(ref, configs, transport=transport())
    artifact = normalize_article(raw)

    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_store.save(artifact)
    loaded = artifact_store.load(artifact.article_id)

    dedupe_store = DedupeStore(tmp_path / "dedupe")
    cluster = merge_into_cluster(loaded, dedupe_store)
    clustered_snapshot = dedupe_store.load_article_snapshot(loaded.article_id)

    assert loaded.source_reference == raw.source_reference
    assert loaded.language == "en"
    assert loaded.license_tag == "site-terms"
    assert loaded.reliability_tier == "B"
    assert "<" not in loaded.body_text
    assert ">" not in loaded.body_text
    assert "Subscribe now" not in loaded.body_text
    assert cluster.member_article_ids == [loaded.article_id]
    assert clustered_snapshot.cluster_id == cluster.cluster_id
    assert dedupe_store.cluster_for_article(loaded.article_id) == cluster
