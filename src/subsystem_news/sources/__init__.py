"""Source discovery, fetch, and approved-source access policy checks."""

from __future__ import annotations

from subsystem_news.sources.base import (
    FetchTrace,
    HttpResponse,
    HttpTransport,
    NewsArticleRef,
    RawArticleFetch,
    SourceAdapter,
    UrllibHttpTransport,
)
from subsystem_news.sources.discover import discover_articles, fetch_article_body
from subsystem_news.sources.registry import AdapterRegistry, default_registry
from subsystem_news.sources.trace import load_fetch_trace, write_fetch_trace

__all__ = [
    "AdapterRegistry",
    "FetchTrace",
    "HttpResponse",
    "HttpTransport",
    "NewsArticleRef",
    "RawArticleFetch",
    "SourceAdapter",
    "UrllibHttpTransport",
    "default_registry",
    "discover_articles",
    "fetch_article_body",
    "load_fetch_trace",
    "write_fetch_trace",
]
