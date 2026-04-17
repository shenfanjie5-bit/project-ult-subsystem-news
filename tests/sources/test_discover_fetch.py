from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from subsystem_news.contracts import NewsSourceConfig, SourceReference, SourceReferenceLocator, load_allowlist
from subsystem_news.errors import SourceNotApprovedError
from subsystem_news.sources import (
    HttpResponse,
    NewsArticleRef,
    discover_articles,
    fetch_article_body,
)


FIXTURE_DIR = Path("src/subsystem_news/fixtures")
SOURCES_DIR = FIXTURE_DIR / "sources"
VALID_ALLOWLIST = FIXTURE_DIR / "approved_sources.valid.sample.json"


class StaticTransport:
    def __init__(self, responses: Mapping[str, str]) -> None:
        self._responses = dict(responses)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        del headers
        return HttpResponse(url=url, status_code=200, text=self._responses[url], headers={})


def load_configs() -> list[NewsSourceConfig]:
    return load_allowlist(VALID_ALLOWLIST)


def transport(
    *,
    rss: str | None = None,
    api: str | None = None,
    html: str | None = None,
) -> StaticTransport:
    configs = {config.source_id: config for config in load_configs()}
    return StaticTransport(
        {
            str(configs["global-wire-rss"].base_url): rss
            if rss is not None
            else (SOURCES_DIR / "rss_feed.xml").read_text(encoding="utf-8"),
            str(configs["market-filings-api"].base_url): api
            if api is not None
            else (SOURCES_DIR / "api_articles.json").read_text(encoding="utf-8"),
            str(configs["company-site-html"].base_url): html
            if html is not None
            else (SOURCES_DIR / "site_page.html").read_text(encoding="utf-8"),
        },
    )


def config_for(source_id: str) -> NewsSourceConfig:
    return next(config for config in load_configs() if config.source_id == source_id)


def test_discover_articles_rejects_unapproved_config_even_when_constructed_directly() -> None:
    source = NewsSourceConfig.model_validate(
        {
            "source_id": "unapproved-blog",
            "display_name": "Unapproved Blog",
            "access_mode": "site_html",
            "base_url": "https://blog.example.com/news",
            "approved": False,
            "reliability_tier": "C",
            "license_tag": "unknown",
            "language": "en",
            "credential_ref": None,
        },
    )

    with pytest.raises(SourceNotApprovedError):
        discover_articles([source], transport=transport())


def test_fetch_article_body_rejects_ref_outside_current_allowlist() -> None:
    configs = load_configs()
    refs = discover_articles([config_for("global-wire-rss")], transport=transport())

    with pytest.raises(SourceNotApprovedError):
        fetch_article_body(refs[0], configs=[config_for("market-filings-api")], transport=transport())


def test_rss_adapter_discovers_guid_link_title_and_pubdate() -> None:
    refs = discover_articles([config_for("global-wire-rss")], transport=transport())

    assert len(refs) == 2
    assert refs[0].provider_key == "wire-article-1"
    assert refs[0].url == "https://news.example.com/articles/acme-contract"
    assert refs[0].title_hint == "Acme signs supply contract"
    assert refs[0].published_at_hint is not None


def test_rss_fetch_returns_raw_fields_and_stable_content_hash() -> None:
    rss_source = config_for("global-wire-rss")
    refs = discover_articles([rss_source], transport=transport())

    first_fetch = fetch_article_body(refs[0], [rss_source], transport=transport())
    second_fetch = fetch_article_body(refs[0], [rss_source], transport=transport())
    changed_feed = (SOURCES_DIR / "rss_feed.xml").read_text(encoding="utf-8").replace(
        "supply contract with Globex",
        "supply contract update with Globex",
    )
    changed_fetch = fetch_article_body(refs[0], [rss_source], transport=transport(rss=changed_feed))

    assert first_fetch.raw_title == "Acme signs supply contract"
    assert first_fetch.raw_body == "Acme Corp announced a supply contract with Globex Inc."
    assert first_fetch.summary == "Acme announced a supply agreement summary."
    assert first_fetch.content_hash == second_fetch.content_hash
    assert first_fetch.content_hash != changed_fetch.content_hash


def test_api_adapter_discovers_and_fetches_provider_key_article() -> None:
    api_source = config_for("market-filings-api")
    refs = discover_articles([api_source], transport=transport())

    assert len(refs) == 1
    assert refs[0].provider_key == "filing-2026-001"

    fetch = fetch_article_body(refs[0], [api_source], transport=transport())

    assert fetch.raw_title == "Globex files merger update"
    assert fetch.raw_body == "Globex filed an update describing the pending merger review."
    assert fetch.summary == "Globex filed a merger update."


def test_site_html_adapter_fetches_raw_html_title_and_body_candidate() -> None:
    html_source = config_for("company-site-html")
    refs = discover_articles([html_source], transport=transport())
    fetch = fetch_article_body(refs[0], [html_source], transport=transport())

    assert len(refs) == 1
    assert fetch.raw_title == "Acme contract update"
    assert fetch.raw_html is not None
    assert "<title>Acme contract update</title>" in fetch.raw_html
    assert fetch.raw_body is not None
    assert "<article>" in fetch.raw_body


def test_news_article_ref_rejects_empty_or_mismatched_source_reference() -> None:
    with pytest.raises(ValidationError):
        NewsArticleRef.model_validate(
            {
                "source_id": "global-wire-rss",
                "source_reference": {},
                "url": "https://news.example.com/articles/1",
            },
        )

    source_reference = SourceReference(
        source_id="other-source",
        url="https://news.example.com/articles/1",
        provider_key=None,
        original_locator=SourceReferenceLocator(
            locator_type="rss_link",
            locator_value="https://news.example.com/articles/1",
        ),
    )
    with pytest.raises(ValidationError) as exc_info:
        NewsArticleRef(
            source_id="global-wire-rss",
            source_reference=source_reference,
            url="https://news.example.com/articles/1",
        )

    assert "source_reference.source_id must match source_id" in str(exc_info.value)


def test_raw_fetch_does_not_expose_normalized_artifact_fields() -> None:
    api_source = config_for("market-filings-api")
    ref = discover_articles([api_source], transport=transport())[0]
    fetch = fetch_article_body(ref, [api_source], transport=transport())

    assert "title" not in type(fetch).model_fields
    assert "body_text" not in type(fetch).model_fields
    assert "published_at" not in type(fetch).model_fields
