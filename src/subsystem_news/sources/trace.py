"""Fetch trace persistence for source-layer raw payloads."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from subsystem_news.errors import ContractViolationError
from subsystem_news.sources.base import FetchTrace, RawArticleFetch


_SAFE_TRACE_ID_PATTERN = re.compile(r"^fetch-[0-9a-f]{24}$")


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

    if _SAFE_TRACE_ID_PATTERN.fullmatch(trace.trace_id) is None:
        raise ContractViolationError(f"unsafe fetch trace_id: {trace.trace_id}")

    trace_root = trace_dir.resolve()
    path = trace_root / f"{trace.trace_id}.json"
    resolved_path = path.resolve(strict=False)
    if not resolved_path.is_relative_to(trace_root):
        raise ContractViolationError(f"fetch trace path escapes trace_dir: {trace.trace_id}")

    try:
        with resolved_path.open("x", encoding="utf-8") as trace_file:
            trace_file.write(f"{trace.model_dump_json(indent=2)}\n")
    except FileExistsError as exc:
        raise ContractViolationError(f"fetch trace already exists: {trace.trace_id}") from exc
    return path


def load_fetch_trace(path: Path) -> FetchTrace:
    """Load and validate a persisted source fetch trace."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return FetchTrace.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ContractViolationError(f"invalid fetch trace: {path}") from exc
