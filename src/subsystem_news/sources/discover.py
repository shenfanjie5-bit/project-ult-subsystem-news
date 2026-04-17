"""Approved-source discovery and fetch policy checks."""

from __future__ import annotations

from typing import Mapping, Sequence

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
    """Discover article references from approved source configs only."""

    active_registry = registry or default_registry()
    refs: list[NewsArticleRef] = []
    for config in configs:
        _ensure_approved(config)
        adapter = active_registry.get(config.access_mode)
        discovered = adapter.discover(config, cursor=cursor, transport=transport)
        for ref in discovered:
            _validate_discovered_ref(ref, config)
        refs.extend(discovered)
    return refs


def fetch_article_body(
    ref: NewsArticleRef,
    configs: Sequence[NewsSourceConfig],
    *,
    registry: AdapterRegistry | None = None,
    transport: HttpTransport | None = None,
) -> RawArticleFetch:
    """Fetch a raw article body only when its source is in the active allowlist."""

    config = _find_source(ref.source_id, configs)
    _ensure_approved(config)
    active_registry = registry or default_registry()
    adapter = active_registry.get(config.access_mode)
    fetch = adapter.fetch(ref, config, transport=transport)
    _validate_fetch(fetch, ref, config)
    return fetch


def _ensure_approved(config: NewsSourceConfig) -> None:
    if config.approved is not True:
        raise SourceNotApprovedError(f"source is not approved: {config.source_id}")


def _find_source(source_id: str, configs: Sequence[NewsSourceConfig]) -> NewsSourceConfig:
    for config in configs:
        if config.source_id == source_id:
            return config
    raise SourceNotApprovedError(f"source is not in the active allowlist: {source_id}")


def _validate_discovered_ref(ref: NewsArticleRef, config: NewsSourceConfig) -> None:
    if ref.source_id != config.source_id:
        raise ContractViolationError("adapter returned ref for a different source_id")
    if ref.source_reference.source_id != ref.source_id:
        raise ContractViolationError("adapter returned mismatched source_reference.source_id")
    if ref.url is None and ref.provider_key is None:
        raise ContractViolationError("adapter returned untraceable article ref")


def _validate_fetch(
    fetch: RawArticleFetch,
    ref: NewsArticleRef,
    config: NewsSourceConfig,
) -> None:
    if fetch.source.source_id != config.source_id:
        raise ContractViolationError("adapter returned fetch for a different source")
    if fetch.ref.source_reference != ref.source_reference:
        raise ContractViolationError("adapter returned fetch for a different source_reference")
    if fetch.ref.source_id != ref.source_id:
        raise ContractViolationError("adapter returned fetch for a different source_id")
