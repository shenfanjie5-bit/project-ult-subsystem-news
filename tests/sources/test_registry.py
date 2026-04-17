from __future__ import annotations

import pytest

from subsystem_news.errors import ContractViolationError
from subsystem_news.sources import AdapterRegistry, default_registry
from subsystem_news.sources.rss import RssSourceAdapter


def test_default_registry_resolves_supported_access_modes() -> None:
    registry = default_registry()

    assert registry.get("rss").access_mode == "rss"
    assert registry.get("api").access_mode == "api"
    assert registry.get("site_html").access_mode == "site_html"


def test_registry_rejects_duplicate_access_mode() -> None:
    registry = AdapterRegistry()
    registry.register(RssSourceAdapter())

    with pytest.raises(ContractViolationError) as exc_info:
        registry.register(RssSourceAdapter())

    assert "duplicate" in str(exc_info.value)


def test_registry_rejects_unknown_access_mode() -> None:
    registry = AdapterRegistry()

    with pytest.raises(ContractViolationError) as exc_info:
        registry.get("crawler")

    assert "unknown source access_mode" in str(exc_info.value)
