"""Command-line entry point for runtime ingest."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse

from subsystem_news.entities.resolver_client import (
    HttpEntityRegistryClient,
    StubEntityRegistryClient,
)
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.runtime_client import DefaultReasonerRuntimeClient
from subsystem_news.runtime.models import PipelineConfig
from subsystem_news.runtime.orchestrator import run_once
from subsystem_news.runtime.replay import replay_artifact_snapshot, replay_trace
from subsystem_news.sources.base import HttpResponse


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="subsystem-news-runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--allowlist", required=True)
    ingest.add_argument("--state-dir", required=True)
    ingest.add_argument("--trace-dir", required=True)
    ingest.add_argument("--cursor-json")
    ingest.add_argument("--dry-run", action="store_true")

    replay = subparsers.add_parser("replay")
    replay_input = replay.add_mutually_exclusive_group(required=True)
    replay_input.add_argument("--trace")
    replay_input.add_argument("--artifact")
    replay.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "replay":
        entity_client, reasoner_client = _replay_clients(dry_run=args.dry_run)
        if args.trace is not None:
            result = replay_trace(
                Path(args.trace),
                entity_client=entity_client,
                reasoner_client=reasoner_client,
            )
        else:
            result = replay_artifact_snapshot(
                Path(args.artifact),
                entity_client=entity_client,
                reasoner_client=reasoner_client,
            )
        print(result.model_dump_json(indent=2))
        return 1 if result.error_count or result.changed_count else 0

    if args.command != "ingest":
        parser.error(f"unsupported command: {args.command}")

    state_dir = Path(args.state_dir)
    allowlist_path = Path(args.allowlist)
    trace_dir = Path(args.trace_dir)
    source_cursor = _parse_cursor(args.cursor_json)
    config = PipelineConfig(
        allowlist_path=allowlist_path,
        artifact_root=state_dir / "artifacts",
        dedupe_root=state_dir / "dedupe",
        trace_root=trace_dir,
        dry_run=args.dry_run,
    )

    result = run_once(
        config,
        source_cursor=source_cursor,
        transport=_sample_fixture_transport() if args.dry_run else None,
    )
    if result.trace_path is not None:
        print(result.trace_path)
    return 1 if result.error_count else 0


def _parse_cursor(raw_cursor: str | None) -> Mapping[str, str] | None:
    if raw_cursor is None:
        return None
    payload = json.loads(raw_cursor)
    if not isinstance(payload, dict):
        raise ContractViolationError("--cursor-json must decode to an object")
    cursor: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ContractViolationError("--cursor-json entries must be strings")
        cursor[key] = value
    return cursor


class _StaticTransport:
    def __init__(self, responses: Mapping[str, str]) -> None:
        self._responses = responses

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        del headers
        try:
            text = self._responses[url]
        except KeyError as exc:
            raise ContractViolationError(f"no dry-run fixture response for {url}") from exc
        return HttpResponse(url=url, status_code=200, text=text, headers={})


def _sample_fixture_transport() -> _StaticTransport:
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures" / "sources"
    return _StaticTransport(
        {
            "https://news.example.com/rss": (fixture_root / "rss_feed.xml").read_text(
                encoding="utf-8"
            ),
            "https://filings.example.com/api/news": (
                fixture_root / "api_response.json"
            ).read_text(encoding="utf-8"),
            "https://site.example.com/markets/plant-update": (
                fixture_root / "site_page.html"
            ).read_text(encoding="utf-8"),
        }
    )


def _replay_clients(dry_run: bool):
    if dry_run:
        return StubEntityRegistryClient(), _NoopReasonerRuntimeClient()

    base_url = (
        os.environ.get("SUBSYSTEM_NEWS_ENTITY_REGISTRY_URL")
        or os.environ.get("ENTITY_REGISTRY_URL")
        or ""
    ).strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ContractViolationError(
            "replay requires --dry-run or an entity-registry URL in "
            "SUBSYSTEM_NEWS_ENTITY_REGISTRY_URL or ENTITY_REGISTRY_URL"
        )
    return HttpEntityRegistryClient(base_url), DefaultReasonerRuntimeClient()


class _NoopReasonerRuntimeClient:
    def generate_structured(self, request: object) -> Mapping[str, object]:
        del request
        return {"facts": []}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
