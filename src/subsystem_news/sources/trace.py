"""Fetch trace persistence for source-layer raw payloads."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from subsystem_news.errors import ContractViolationError
from subsystem_news.sources.base import FetchTrace, RawArticleFetch


def write_fetch_trace(fetch: RawArticleFetch, trace_dir: Path) -> Path:
    """Write source trace metadata without storing full raw article body text."""

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
    path.write_text(f"{trace.model_dump_json(indent=2)}\n", encoding="utf-8")
    return path


def load_fetch_trace(path: Path) -> FetchTrace:
    """Load and validate a persisted source fetch trace."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return FetchTrace.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ContractViolationError(f"invalid fetch trace: {path}") from exc
