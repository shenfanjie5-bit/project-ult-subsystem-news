"""Fetch trace serialization."""

from __future__ import annotations

from pathlib import Path

from subsystem_news.sources.base import FetchTrace, RawArticleFetch


def write_fetch_trace(fetch: RawArticleFetch, trace_dir: Path) -> Path:
    """Write a body-free fetch trace JSON file."""

    trace_dir.mkdir(parents=True, exist_ok=True)
    trace = FetchTrace(
        trace_id=fetch.trace_id,
        source_id=fetch.ref.source_id,
        source_reference=fetch.ref.source_reference,
        url=fetch.ref.url,
        provider_key=fetch.ref.provider_key,
        content_hash=fetch.content_hash,
        fetched_at=fetch.fetched_at,
        error_code=None,
    )
    path = trace_dir / f"{trace.trace_id}.json"
    path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_fetch_trace(path: Path) -> FetchTrace:
    """Load a fetch trace JSON file."""

    return FetchTrace.model_validate_json(path.read_text(encoding="utf-8"))
