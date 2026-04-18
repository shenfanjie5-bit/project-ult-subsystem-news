from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.entities import Mention, dedupe_mentions, detect_mentions


FIXTURE_ROOT = Path("src/subsystem_news/fixtures/entities")


def load_article(name: str) -> NewsArticleArtifact:
    return NewsArticleArtifact.model_validate(json.loads((FIXTURE_ROOT / name).read_text()))


def source_text(article: NewsArticleArtifact, mention: Mention) -> str:
    if mention.locator == "title":
        return article.title
    return article.body_text


def test_detect_mentions_finds_expected_deterministic_candidates_and_spans() -> None:
    article = load_article("single_source_standard.json")

    mentions = detect_mentions(article)

    assert {
        (mention.text, mention.type_hint)
        for mention in mentions
    } >= {
        ("Acme Corp", "company"),
        ("Globex Inc", "company"),
        ("NASDAQ:ACME", "stock_code"),
        ("CATL", "standard_abbreviation"),
        ("battery module", "market_theme"),
        ("supply contract", "market_theme"),
    }
    for mention in mentions:
        text = source_text(article, mention)
        assert mention.start_char >= 0
        assert mention.end_char > mention.start_char
        assert text[mention.start_char : mention.end_char] == mention.text
        assert mention.source_reference == article.source_reference


def test_detect_mentions_handles_chinese_company_and_topic_candidates() -> None:
    article = load_article("cross_language_alias.json")

    mentions = detect_mentions(article)

    assert ("宁德时代", "company") in {
        (mention.text, mention.type_hint) for mention in mentions
    }
    assert ("储能系统", "market_theme") in {
        (mention.text, mention.type_hint) for mention in mentions
    }
    for mention in mentions:
        assert source_text(article, mention)[mention.start_char : mention.end_char] == mention.text


def test_detect_mentions_on_normalized_html_fixture_does_not_emit_markup_noise() -> None:
    article = load_article("html_rss_normalized.json")

    mentions = detect_mentions(article)

    assert {mention.text for mention in mentions} == {"Acme Corp", "Globex Inc"}
    assert all("<" not in mention.text and ">" not in mention.text for mention in mentions)
    assert all("Subscribe" not in mention.context for mention in mentions)


def test_dedupe_mentions_prefers_longer_more_specific_overlap() -> None:
    article = load_article("single_source_standard.json")
    short = Mention(
        article_id=article.article_id,
        text="Acme",
        start_char=0,
        end_char=4,
        locator="title",
        type_hint="standard_abbreviation",
        context=article.title,
        source_reference=article.source_reference,
    )
    long = Mention(
        article_id=article.article_id,
        text="Acme Corp",
        start_char=0,
        end_char=9,
        locator="title",
        type_hint="company",
        context=article.title,
        source_reference=article.source_reference,
    )

    deduped = dedupe_mentions([short, long, long])

    assert deduped == [long]


@pytest.mark.parametrize(
    "payload_update",
    [
        {"start_char": -1},
        {"end_char": 0},
        {"text": "   "},
    ],
)
def test_mention_rejects_invalid_offsets_or_empty_text(payload_update: dict[str, object]) -> None:
    article = load_article("single_source_standard.json")
    payload = {
        "article_id": article.article_id,
        "text": "Acme",
        "start_char": 0,
        "end_char": 4,
        "locator": "title",
        "type_hint": "company",
        "context": article.title,
        "source_reference": article.source_reference,
    }
    payload.update(payload_update)

    with pytest.raises(ValidationError):
        Mention.model_validate(payload)
