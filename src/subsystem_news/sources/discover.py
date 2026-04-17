"""Approved-source discovery and fetch orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from subsystem_news.contracts import NewsSourceConfig
from subsystem_news.errors import ContractViolationError, SourceNotApprovedError
from subsystem_news.sources.base import HttpTransport, NewsArticleRef, RawArticleFetch
from subsystem_news.sources.registry import AdapterRegistry, default_registry


def discover_articles(
    configs: Sequence[NewsSourceConfig],
    cursor: Mapping[str, str] | None = None,
    *,
    registry: AdapterRegistry | None = None,
    transport: HttpTransport | None = None,
) -> list[NewsArticleRef]:
    """Discover article references from approved source configs."""

    active_registry = registry or default_registry()
    refs: list[NewsArticleRef] = []
    for config in configs:
        _ensure_approved(config)
        adapter = active_registry.get(config.access_mode)
        refs.extend(adapter.discover(config, cursor, transport=transport))
    return refs


def fetch_article_body(
    ref: NewsArticleRef,
    configs: Sequence[NewsSourceConfig],
    *,
    registry: AdapterRegistry | None = None,
    transport: HttpTransport | None = None,
) -> RawArticleFetch:
    """Fetch a raw article payload for a ref in the current allowlist."""

    source = _source_for_ref(ref, configs)
    adapter = (registry or default_registry()).get(source.access_mode)
    fetch = adapter.fetch(ref, source, transport=transport)
    if fetch.ref.source_reference != ref.source_reference:
        raise ContractViolationError("fetch source_reference must match requested ref")
    if fetch.ref.source_id != ref.source_id:
        raise ContractViolationError("fetch source_id must match requested ref")
    return fetch


def _source_for_ref(ref: NewsArticleRef, configs: Sequence[NewsSourceConfig]) -> NewsSourceConfig:
    for config in configs:
        if config.source_id == ref.source_id:
            _ensure_approved(config)
            return config
    raise SourceNotApprovedError(f"source_id is not in allowlist: {ref.source_id}")


def _ensure_approved(config: NewsSourceConfig) -> None:
    if config.approved is not True:
        raise SourceNotApprovedError(f"source is not approved: {config.source_id}")
