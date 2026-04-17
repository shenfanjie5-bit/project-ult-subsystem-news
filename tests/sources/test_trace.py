from __future__ import annotations

from subsystem_news.sources import discover_articles, fetch_article_body
from subsystem_news.sources.trace import load_fetch_trace, write_fetch_trace

from tests.sources.test_discover_fetch import config_for, transport


def test_fetch_trace_round_trip_excludes_raw_body(tmp_path) -> None:
    api_source = config_for("market-filings-api")
    ref = discover_articles([api_source], transport=transport())[0]
    fetch = fetch_article_body(ref, [api_source], transport=transport())

    path = write_fetch_trace(fetch, tmp_path)
    restored = load_fetch_trace(path)
    serialized = path.read_text(encoding="utf-8")

    assert restored.trace_id == fetch.trace_id
    assert restored.source_reference == fetch.ref.source_reference
    assert restored.content_hash == fetch.content_hash
    assert "Globex filed an update describing the pending merger review." not in serialized
    assert "Globex filed a merger update." not in serialized
