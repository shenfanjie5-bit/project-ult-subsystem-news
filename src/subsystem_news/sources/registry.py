"""Source adapter registry."""

from __future__ import annotations

from subsystem_news.errors import ContractViolationError
from subsystem_news.sources.base import SourceAdapter


class AdapterRegistry:
    """Map approved source access modes to source adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        access_mode = getattr(adapter, "access_mode", None)
        if not isinstance(access_mode, str) or not access_mode:
            raise ContractViolationError("source adapter must define a non-empty access_mode")
        if access_mode in self._adapters:
            raise ContractViolationError(f"source adapter already registered for {access_mode}")
        self._adapters[access_mode] = adapter

    def get(self, access_mode: str) -> SourceAdapter:
        try:
            return self._adapters[access_mode]
        except KeyError as exc:
            raise ContractViolationError(f"no source adapter registered for {access_mode}") from exc


def default_registry() -> AdapterRegistry:
    """Build the default adapter registry for configured source access modes."""

    from subsystem_news.sources.api import ApiSourceAdapter
    from subsystem_news.sources.rss import RssSourceAdapter
    from subsystem_news.sources.site_html import SiteHtmlSourceAdapter

    registry = AdapterRegistry()
    registry.register(RssSourceAdapter())
    registry.register(ApiSourceAdapter())
    registry.register(SiteHtmlSourceAdapter())
    return registry
