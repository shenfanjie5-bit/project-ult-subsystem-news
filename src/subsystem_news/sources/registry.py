"""Source adapter registry."""

from __future__ import annotations

from subsystem_news.errors import ContractViolationError
from subsystem_news.sources.base import SourceAdapter


class AdapterRegistry:
    """Lookup table from source access mode to adapter."""

    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        access_mode = adapter.access_mode
        if not access_mode:
            raise ContractViolationError("source adapter access_mode must be non-empty")
        if access_mode in self._adapters:
            raise ContractViolationError(f"duplicate source adapter registered: {access_mode}")
        self._adapters[access_mode] = adapter

    def get(self, access_mode: str) -> SourceAdapter:
        try:
            return self._adapters[access_mode]
        except KeyError as exc:
            raise ContractViolationError(f"unknown source access_mode: {access_mode}") from exc


def default_registry() -> AdapterRegistry:
    """Return the default registry for supported source access modes."""

    from subsystem_news.sources.api import ApiSourceAdapter
    from subsystem_news.sources.rss import RssSourceAdapter
    from subsystem_news.sources.site_html import SiteHtmlSourceAdapter

    registry = AdapterRegistry()
    registry.register(RssSourceAdapter())
    registry.register(ApiSourceAdapter())
    registry.register(SiteHtmlSourceAdapter())
    return registry
