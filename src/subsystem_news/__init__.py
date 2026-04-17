"""News understanding subsystem package namespace."""

from subsystem_news import (
    dedupe,
    entities,
    extract,
    fixtures,
    graph,
    normalize,
    runtime,
    signals,
    sources,
)
from subsystem_news.version import __version__

__all__ = [
    "__version__",
    "sources",
    "normalize",
    "dedupe",
    "entities",
    "extract",
    "signals",
    "graph",
    "runtime",
    "fixtures",
]
