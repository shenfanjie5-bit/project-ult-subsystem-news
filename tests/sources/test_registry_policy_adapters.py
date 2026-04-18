from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from subsystem_news.contracts import NewsSourceConfig, SourceReference, load_allowlist
from subsystem_news.errors import ContractViolationError, SourceNotApprovedError
from subsystem_news.normalize.pipeline import normalize_article
from subsystem_news.sources import (
    AdapterRegistry,
    HttpResponse,
    NewsArticleRef,
    default_registry,
    discover_articles,
    fetch_article_body,
)
from subsystem_news.sources.base import HttpTransport
from subsystem_news.sources.trace import load_fetch_trace, write_fetch_trace


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
        try:
            text = self._responses[url]
        except KeyError as exc:
            raise AssertionError(f"unexpected network URL: {url}") from exc
        return HttpResponse(url=url, status_code=200, text=text, headers={})


class DuplicateAdapter:
    access_mode = "rss"

    def discover(
        self,
        source: NewsSourceConfig,
        cursor: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> list[NewsArticleRef]:
        del source, cursor, transport
        return []

    def fetch(
        self,
        ref: NewsArticleRef,
        source: NewsSourceConfig,
        *,
        transport: HttpTransport | None = None,
    ):
        del ref, source, transport
        raise NotImplementedError


class RejectingTransport:
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        del url, headers
        raise AssertionError("transport should not be called")


def load_configs() -> list[NewsSourceConfig]:
    return load_allowlist(FIXTURE_ROOT / "approved_sources.valid.sample.json")


def transport() -> StaticTransport:
    return StaticTransport(
        {
            "https://news.example.com/rss": (
                SOURCE_FIXTURE_ROOT / "rss_feed.xml"
            ).read_text(encoding="utf-8"),
            "https://filings.example.com/api/news": (
                SOURCE_FIXTURE_ROOT / "api_response.json"
            ).read_text(encoding="utf-8"),
            "https://site.example.com/markets/plant-update": (
                SOURCE_FIXTURE_ROOT / "site_page.html"
            ).read_text(encoding="utf-8"),
        }
    )


def config_by_id(configs: list[NewsSourceConfig], source_id: str) -> NewsSourceConfig:
    for config in configs:
        if config.source_id == source_id:
            return config
    raise AssertionError(source_id)


def test_default_registry_resolves_known_adapters_and_rejects_unknown() -> None:
    registry = default_registry()

    assert registry.get("rss").access_mode == "rss"
    assert registry.get("api").access_mode == "api"
    assert registry.get("site_html").access_mode == "site_html"
    with pytest.raises(ContractViolationError, match="no source adapter"):
        registry.get("crawler")


def test_registry_rejects_duplicate_access_mode() -> None:
    registry = AdapterRegistry()
    registry.register(DuplicateAdapter())

    with pytest.raises(ContractViolationError, match="already registered"):
        registry.register(DuplicateAdapter())


def test_discover_articles_rejects_unapproved_config_even_without_loader() -> None:
    payload = config_by_id(load_configs(), "site-html").model_dump(mode="json")
    payload["approved"] = False
    unapproved = NewsSourceConfig.model_validate(payload)

    with pytest.raises(SourceNotApprovedError, match="site-html"):
        discover_articles([unapproved], transport=transport())


def test_fetch_article_body_rejects_source_outside_current_allowlist() -> None:
    configs = load_configs()
    refs = discover_articles(configs, transport=transport())
    api_ref = next(ref for ref in refs if ref.source_id == "market-filings-api")
    rss_only = [config_by_id(configs, "global-wire-rss")]

    with pytest.raises(SourceNotApprovedError, match="market-filings-api"):
        fetch_article_body(api_ref, rss_only, transport=transport())


def test_rss_adapter_discovers_and_fetches_fixture_articles() -> None:
    configs = [config_by_id(load_configs(), "global-wire-rss")]
    refs = discover_articles(configs, transport=transport())

    assert len(refs) == 2
    first = refs[0]
    assert first.provider_key == "wire-acme-contract"
    assert first.url == "https://news.example.com/articles/acme-contract"
    assert first.title_hint == "Acme signs a supply contract"
    assert first.published_at_hint is not None
    assert first.source_reference.original_locator.locator_type == "rss_guid"

    fetch = fetch_article_body(first, configs, transport=transport())

    assert fetch.raw_title == "Acme signs a supply contract"
    assert fetch.raw_body == "Acme Corp announced a new supply contract with Globex Inc."
    assert fetch.summary == "Acme Corp announced a new supply agreement with Globex."
    assert fetch.published_at_raw == "Thu, 15 Jan 2026 10:30:00 GMT"
    assert fetch.content_hash == fetch_article_body(first, configs, transport=transport()).content_hash


def test_rss_html_content_is_normalized_from_raw_html() -> None:
    configs = [config_by_id(load_configs(), "global-wire-rss")]
    rss_with_html = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Global Wire</title>
    <item>
      <guid>wire-html-content</guid>
      <link>https://news.example.com/articles/html-content</link>
      <title>Acme raises guidance</title>
      <pubDate>Thu, 15 Jan 2026 10:30:00 GMT</pubDate>
      <description>Acme raised its guidance.</description>
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
    html_transport = StaticTransport({"https://news.example.com/rss": rss_with_html})
    ref = discover_articles(configs, transport=html_transport)[0]

    fetch = fetch_article_body(ref, configs, transport=html_transport)
    artifact = normalize_article(fetch)

    assert fetch.raw_body is None
    assert fetch.raw_html is not None
    assert artifact.body_text == "Acme Corp raised 2026 guidance. Globex Inc remains a supplier."
    assert "<" not in artifact.body_text
    assert ">" not in artifact.body_text
    assert "Subscribe now" not in artifact.body_text
    assert artifact.source_reference == fetch.source_reference


def test_rss_nested_content_encoded_markup_is_normalized_from_raw_html() -> None:
    configs = [config_by_id(load_configs(), "global-wire-rss")]
    rss_with_nested_html = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Global Wire</title>
    <item>
      <guid>wire-nested-html-content</guid>
      <link>https://news.example.com/articles/nested-html-content</link>
      <title>Acme expands capacity</title>
      <pubDate>Thu, 15 Jan 2026 10:30:00 GMT</pubDate>
      <description>Fallback summary should not be used.</description>
      <content:encoded>
        <article>
          <header>Subscribe now</header>
          <p>Acme Corp expanded capacity.</p>
          <p>Globex Inc signed a supply option.</p>
          <script>window.noise = true;</script>
        </article>
      </content:encoded>
    </item>
  </channel>
</rss>"""
    html_transport = StaticTransport({"https://news.example.com/rss": rss_with_nested_html})
    ref = discover_articles(configs, transport=html_transport)[0]

    fetch = fetch_article_body(ref, configs, transport=html_transport)
    artifact = normalize_article(fetch)

    assert fetch.raw_body is None
    assert fetch.raw_html is not None
    assert "<article>" in fetch.raw_html
    assert artifact.body_text == (
        "Acme Corp expanded capacity. Globex Inc signed a supply option."
    )
    assert artifact.body_text != "Fallback summary should not be used."
    assert "<" not in artifact.body_text
    assert "Subscribe now" not in artifact.body_text


def test_atom_xhtml_content_is_normalized_from_raw_html() -> None:
    configs = [config_by_id(load_configs(), "global-wire-rss")]
    atom_with_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Global Wire</title>
  <entry>
    <id>atom-xhtml-content</id>
    <link href="https://news.example.com/articles/atom-xhtml-content"/>
    <title>Acme signs Atom contract</title>
    <updated>2026-01-15T10:30:00Z</updated>
    <summary>Fallback atom summary should not be used.</summary>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
        <header>Subscribe now</header>
        <p>Acme Corp signed an Atom contract.</p>
        <p>Globex Inc remains the supplier.</p>
      </div>
    </content>
  </entry>
</feed>"""
    html_transport = StaticTransport({"https://news.example.com/rss": atom_with_xhtml})
    ref = discover_articles(configs, transport=html_transport)[0]

    fetch = fetch_article_body(ref, configs, transport=html_transport)
    artifact = normalize_article(fetch)

    assert fetch.raw_body is None
    assert fetch.raw_html is not None
    assert "<p>Acme Corp signed an Atom contract.</p>" in fetch.raw_html
    assert artifact.body_text == (
        "Acme Corp signed an Atom contract. Globex Inc remains the supplier."
    )
    assert artifact.body_text != "Fallback atom summary should not be used."
    assert "<" not in artifact.body_text
    assert "Subscribe now" not in artifact.body_text


def test_api_adapter_discovers_and_fetches_provider_key_article() -> None:
    configs = [config_by_id(load_configs(), "market-filings-api")]
    refs = discover_articles(configs, transport=transport())

    assert len(refs) == 1
    ref = refs[0]
    assert ref.provider_key == "filing-2026-0001"
    assert ref.source_reference.provider_key == "filing-2026-0001"

    fetch = fetch_article_body(ref, configs, transport=transport())

    assert fetch.raw_body.startswith("Globex Inc filed a notice")
    assert fetch.summary == "Globex filed a proposed acquisition notice."
    assert fetch.author_or_channel == "Filings API"


def test_site_html_adapter_fetches_raw_html_and_title_hint() -> None:
    configs = [config_by_id(load_configs(), "site-html")]
    refs = discover_articles(configs, transport=transport())

    assert len(refs) == 1
    ref = refs[0]
    assert ref.url == "https://site.example.com/markets/plant-update"
    assert ref.source_reference.url is not None

    fetch = fetch_article_body(ref, configs, transport=transport())

    assert "<title>Plant restart update</title>" in fetch.raw_html
    assert fetch.raw_title == "Plant restart update"
    assert "North River Metals restarted its nickel plant" in (fetch.raw_body or "")


def test_site_html_adapter_rejects_url_outside_approved_base_before_network() -> None:
    configs = [config_by_id(load_configs(), "site-html")]
    unapproved_url = "https://evil.example.com/markets/plant-update"
    source_reference = SourceReference.model_validate(
        {
            "source_id": "site-html",
            "url": unapproved_url,
            "provider_key": None,
            "original_locator": {
                "locator_type": "page_url",
                "locator_value": unapproved_url,
            },
        }
    )
    ref = NewsArticleRef(
        source_id="site-html",
        source_reference=source_reference,
        url=unapproved_url,
    )

    with pytest.raises(ContractViolationError, match="approved base_url"):
        fetch_article_body(ref, configs, transport=RejectingTransport())


def test_site_html_adapter_rejects_redirect_outside_approved_base_url() -> None:
    configs = [config_by_id(load_configs(), "site-html")]
    ref = discover_articles(configs, transport=transport())[0]

    class RedirectTransport:
        def get(
            self,
            url: str,
            *,
            headers: Mapping[str, str] | None = None,
        ) -> HttpResponse:
            del url, headers
            return HttpResponse(
                url="https://evil.example.com/redirected",
                status_code=200,
                text=(SOURCE_FIXTURE_ROOT / "site_page.html").read_text(encoding="utf-8"),
                headers={},
            )

    with pytest.raises(ContractViolationError, match="redirect target"):
        fetch_article_body(ref, configs, transport=RedirectTransport())


@pytest.mark.parametrize(
    "source_id,redirect_text",
    [
        ("market-filings-api", (SOURCE_FIXTURE_ROOT / "api_response.json").read_text(encoding="utf-8")),
        ("global-wire-rss", (SOURCE_FIXTURE_ROOT / "rss_feed.xml").read_text(encoding="utf-8")),
    ],
)
def test_api_and_rss_adapters_reject_redirect_outside_approved_base_url(
    source_id: str,
    redirect_text: str,
) -> None:
    configs = [config_by_id(load_configs(), source_id)]

    class RedirectTransport:
        def get(
            self,
            url: str,
            *,
            headers: Mapping[str, str] | None = None,
        ) -> HttpResponse:
            del url, headers
            return HttpResponse(
                url="https://evil.example.com/redirected",
                status_code=200,
                text=redirect_text,
                headers={},
            )

    with pytest.raises(ContractViolationError, match="redirect target"):
        discover_articles(configs, transport=RedirectTransport())


def test_fetch_trace_round_trip_excludes_body_text(tmp_path: Path) -> None:
    configs = [config_by_id(load_configs(), "market-filings-api")]
    ref = discover_articles(configs, transport=transport())[0]
    fetch = fetch_article_body(ref, configs, transport=transport())

    path = write_fetch_trace(fetch, tmp_path)
    restored = load_fetch_trace(path)
    trace_json = path.read_text(encoding="utf-8")

    assert restored.trace_id == fetch.trace_id
    assert restored.source_reference == fetch.ref.source_reference
    assert restored.content_hash == fetch.content_hash
    assert "Globex Inc filed a notice" not in trace_json
    assert "summary" not in trace_json


def test_write_fetch_trace_rejects_path_traversal_trace_id(tmp_path: Path) -> None:
    configs = [config_by_id(load_configs(), "market-filings-api")]
    ref = discover_articles(configs, transport=transport())[0]
    fetch = fetch_article_body(ref, configs, transport=transport())
    malformed_fetch = fetch.model_copy(update={"trace_id": "../outside"})
    trace_dir = tmp_path / "traces"

    with pytest.raises(ContractViolationError, match="unsafe fetch trace_id"):
        write_fetch_trace(malformed_fetch, trace_dir)

    assert not (tmp_path / "outside.json").exists()


def test_fetch_article_body_rejects_adapter_source_reference_drift() -> None:
    configs = [config_by_id(load_configs(), "global-wire-rss")]
    ref = discover_articles(configs, transport=transport())[0]
    mismatched_reference = SourceReference.model_validate(
        {
            "source_id": ref.source_id,
            "url": "https://news.example.com/articles/other",
            "provider_key": "wire-other",
            "original_locator": {
                "locator_type": "rss_guid",
                "locator_value": "wire-other",
            },
        }
    )
    mismatched_ref = NewsArticleRef(
        source_id=ref.source_id,
        source_reference=mismatched_reference,
    )

    with pytest.raises(ContractViolationError, match="not found"):
        fetch_article_body(mismatched_ref, configs, transport=transport())
