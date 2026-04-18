from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from subsystem_news.contracts import NewsSourceConfig, load_allowlist
from subsystem_news.entities import (
    StubEntityRegistryClient,
    detect_mentions,
    resolve_article_entities,
)
from subsystem_news.normalize.pipeline import normalize_article
from subsystem_news.sources import HttpResponse, discover_articles, fetch_article_body
from subsystem_news.sources.base import HttpTransport, RawArticleFetch


FIXTURE_ROOT = Path("src/subsystem_news/fixtures")


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


def config_by_id(configs: list[NewsSourceConfig], source_id: str) -> NewsSourceConfig:
    for config in configs:
        if config.source_id == source_id:
            return config
    raise AssertionError(source_id)


def test_source_normalize_entities_integration_preserves_clean_source_reference_spans() -> None:
    rss_with_html = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Global Wire</title>
    <item>
      <guid>wire-html-entity</guid>
      <link>https://news.example.com/articles/html-entity</link>
      <title>Acme raises guidance</title>
      <pubDate>Thu, 15 Jan 2026 10:30:00 GMT</pubDate>
      <description>Fallback summary should not be used.</description>
      <content:encoded><![CDATA[
        <article>
          <header>Subscribe now</header>
          <p>Acme Corp raised 2026 guidance.</p>
          <p>Globex Inc remains a supplier.</p>
          <script>window.noise = true;</script>
        </article>
      ]]></content:encoded>
    </item>
  </channel>
</rss>"""
    configs = [config_by_id(load_allowlist(FIXTURE_ROOT / "approved_sources.valid.sample.json"), "global-wire-rss")]
    transport: HttpTransport = StaticTransport({"https://news.example.com/rss": rss_with_html})
    ref = discover_articles(configs, transport=transport)[0]
    fetch = fetch_article_body(ref, configs, transport=transport)
    article = normalize_article(fetch)
    client = StubEntityRegistryClient(
        alias_results={
            ("Acme Corp", "company"): {"canonical_id": "entity:acme"},
            ("Globex Inc", "company"): {"canonical_id": "entity:globex"},
        }
    )

    mentions = detect_mentions(article)
    entities = resolve_article_entities(article, client)

    assert article.body_text == "Acme Corp raised 2026 guidance. Globex Inc remains a supplier."
    assert article.source_reference == fetch.source_reference
    assert "<" not in article.body_text
    assert "Subscribe now" not in article.body_text
    for mention in mentions:
        assert article.body_text[mention.start_char : mention.end_char] == mention.text
        assert mention.source_reference == article.source_reference
    assert [(entity.mention_text, entity.canonical_id) for entity in entities] == [
        ("Acme Corp", "entity:acme"),
        ("Globex Inc", "entity:globex"),
    ]


def test_summary_only_artifact_produces_unresolved_low_coverage_entities() -> None:
    raw = RawArticleFetch.model_validate(
        json.loads((FIXTURE_ROOT / "normalize/chinese_rss_summary.json").read_text())
    )
    article = normalize_article(raw)
    client = StubEntityRegistryClient()

    entities = resolve_article_entities(article, client)

    assert article.body_text.startswith("宁德时代公告称")
    assert entities
    assert all(entity.resolution_status == "unresolved" for entity in entities)
    assert all(entity.canonical_id is None for entity in entities)
