from __future__ import annotations

import json
from pathlib import Path

import pytest

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.errors import ContractViolationError
from subsystem_news.normalize.pipeline import (
    article_id_for,
    normalize_article,
    parse_article,
    select_body_text,
)
from subsystem_news.sources.base import RawArticleFetch


FIXTURE_ROOT = Path("src/subsystem_news/fixtures/normalize")


def load_raw(name: str) -> RawArticleFetch:
    return RawArticleFetch.model_validate(json.loads((FIXTURE_ROOT / name).read_text()))


def test_select_body_text_prefers_raw_body_over_html_and_summary() -> None:
    raw = load_raw("single_source_en.json")

    selected = select_body_text(raw)

    assert "Acme Corp announced a new supply contract" in selected
    assert "HTML copy must not be selected" not in selected
    assert "shorter summary" not in selected


def test_parse_article_uses_html_when_native_body_is_missing() -> None:
    parsed = parse_article(load_raw("site_html_article.json"))

    assert parsed.body_text_source == "raw_html"
    assert parsed.text_quality == "full_text"
    assert "North River Metals restarted its nickel plant" in parsed.body_text
    assert "Subscribe now" not in parsed.body_text
    assert "window.noise" not in parsed.body_text


def test_summary_only_article_is_marked_before_artifact_conversion() -> None:
    parsed = parse_article(load_raw("chinese_rss_summary.json"))
    artifact = normalize_article(load_raw("chinese_rss_summary.json"))

    assert parsed.body_text_source == "summary"
    assert parsed.text_quality == "summary_only"
    assert artifact.body_text.startswith("宁德时代公告称")
    assert artifact.language == "zh"
    assert artifact.cluster_id is None


def test_missing_body_is_rejected() -> None:
    with pytest.raises(ContractViolationError, match="no body text"):
        normalize_article(load_raw("missing_body.json"))


def test_normalize_article_returns_contract_artifact_with_traceable_reference() -> None:
    artifact = normalize_article(load_raw("single_source_en.json"))

    assert isinstance(artifact, NewsArticleArtifact)
    assert artifact.source_id == "global-wire-rss"
    assert artifact.source_reference.source_id == artifact.source_id
    assert artifact.title == "Acme & Globex sign a supply contract"
    assert artifact.author_or_channel == "Markets Desk"
    assert artifact.cluster_id is None
    assert artifact.content_hash.startswith("sha256:")
    assert artifact.article_fingerprint.startswith("sha256:")


def test_article_artifact_json_roundtrip_preserves_content() -> None:
    artifact = normalize_article(load_raw("single_source_en.json"))

    restored = NewsArticleArtifact.model_validate_json(artifact.model_dump_json())

    assert restored == artifact


def test_article_id_for_is_stable_and_locator_sensitive() -> None:
    source_reference = load_raw("single_source_en.json").source_reference
    other_reference = SourceReference.model_validate(
        {
            "source_id": "global-wire-rss",
            "url": "https://news.example.com/articles/other",
            "provider_key": "wire-other",
            "original_locator": {
                "locator_type": "rss_guid",
                "locator_value": "wire-other",
            },
        }
    )

    assert article_id_for(source_reference) == article_id_for(source_reference)
    assert article_id_for(source_reference) != article_id_for(other_reference)
