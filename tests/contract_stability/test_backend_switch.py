from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from subsystem_news.contracts import load_allowlist
from subsystem_news.contracts.candidates import NewsFactCandidate, NewsSignalCandidate
from subsystem_news.entities.resolver_client import (
    RegistryLookup,
    RegistryMention,
    RegistryResolution,
    ResolutionCase,
    StubEntityRegistryClient,
)
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.runtime.backend_config import RuntimeBackendConfig, resolve_reasoner_client
from subsystem_news.runtime.models import PipelineConfig, PipelineRunResult
from subsystem_news.runtime.orchestrator import run_once
from subsystem_news.signals.aggregator import build_signal_candidate
from subsystem_news.signals.direction_judge import judge_direction
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN
from tests.integration.test_milestone3_pipeline import (
    FIXTURE_ROOT,
    FakeReasonerRuntimeClient,
    FakeSdkClient,
    StaticTransport,
)


FROZEN_EX2_FIELDS = frozenset(NewsSignalCandidate.model_fields)


class _RecordingReasonerClient:
    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = response
        self.requests: list[StructuredGenerationRequest] = []

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        self.requests.append(request)
        return self.response


def test_backend_switch_preserves_structured_request_and_ex2_payload() -> None:
    fact = _load_fact("positive_operating_event.json")
    response = {
        "judgement": {
            "signal_type": "event_impact",
            "direction": "positive",
            "impact_scope": "company",
            "time_horizon": "short",
            "rationale": "The same runtime judgement is returned by both backends.",
            "confidence": 0.84,
        }
    }
    clients: dict[str, _RecordingReasonerClient] = {}
    factories = {
        "runtime-a": _factory("runtime-a", response, clients),
        "runtime-b": _factory("runtime-b", response, clients),
    }

    first = resolve_reasoner_client(
        RuntimeBackendConfig(backend_name="runtime-a", provider="managed-a"),
        factories=factories,
    )
    second = resolve_reasoner_client(
        RuntimeBackendConfig(backend_name="runtime-b", provider="managed-b"),
        factories=factories,
    )

    first_judgement = judge_direction(fact, first)
    second_judgement = judge_direction(fact, second)
    first_signal = build_signal_candidate(fact, first_judgement, magnitude="medium")
    second_signal = build_signal_candidate(fact, second_judgement, magnitude="medium")
    first_request = clients["runtime-a"].requests[0]
    second_request = clients["runtime-b"].requests[0]

    assert _request_contract_surface(first_request) == _request_contract_surface(
        second_request
    )
    assert _request_contract_surface(first_request) == {
        "schema_name": SIGNAL_SCHEMA_PIN.schema_name,
        "schema_version": SIGNAL_SCHEMA_PIN.schema_version,
        "contract": "Ex-2",
        "model_output_version": SIGNAL_SCHEMA_PIN.model_output_version,
        "input_payload": first_request.input_payload,
    }
    assert first_request.input_payload == second_request.input_payload
    assert first_signal.model_dump(mode="json") == second_signal.model_dump(mode="json")
    assert frozenset(first_signal.model_dump(mode="json")) == FROZEN_EX2_FIELDS


def test_run_once_backend_registry_switch_preserves_runtime_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_api_fetch_time(monkeypatch)
    clients: dict[str, FakeReasonerRuntimeClient] = {}
    factories = {
        "runtime-a": _runtime_factory("runtime-a", clients),
        "runtime-b": _runtime_factory("runtime-b", clients),
    }

    first = _run_once_with_backend(
        tmp_path / "runtime-a",
        monkeypatch,
        backend_name="runtime-a",
        factories=factories,
    )
    second = _run_once_with_backend(
        tmp_path / "runtime-b",
        monkeypatch,
        backend_name="runtime-b",
        factories=factories,
    )

    assert first.error_count == 0
    assert second.error_count == 0
    assert first.dry_run is False
    assert second.dry_run is False
    assert clients["runtime-a"].requests
    assert [
        request.model_dump(mode="json")
        for request in clients["runtime-a"].requests
    ] == [
        request.model_dump(mode="json") for request in clients["runtime-b"].requests
    ]

    first_ex2_payloads = _ex2_payloads(first)
    second_ex2_payloads = _ex2_payloads(second)
    assert first_ex2_payloads
    assert first_ex2_payloads == second_ex2_payloads
    assert _runtime_contract_snapshot(first) == _runtime_contract_snapshot(second)


def _factory(
    name: str,
    response: Mapping[str, object],
    clients: dict[str, _RecordingReasonerClient],
):
    def _create(config: RuntimeBackendConfig) -> _RecordingReasonerClient:
        assert config.backend_name == name
        clients[name] = _RecordingReasonerClient(response)
        return clients[name]

    return _create


def _runtime_factory(
    name: str,
    clients: dict[str, FakeReasonerRuntimeClient],
):
    def _create(config: RuntimeBackendConfig) -> FakeReasonerRuntimeClient:
        assert config.backend_name == name
        client = FakeReasonerRuntimeClient()
        clients[name] = client
        return client

    return _create


def _run_once_with_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend_name: str,
    factories: Mapping[str, Any],
) -> PipelineRunResult:
    monkeypatch.setenv("SUBSYSTEM_NEWS_REASONER_BACKEND", backend_name)
    monkeypatch.setenv(
        "SUBSYSTEM_NEWS_REASONER_CONFIG_VERSION",
        "runtime_backend_config.v1",
    )
    monkeypatch.delenv("SUBSYSTEM_NEWS_REASONER_PROVIDER", raising=False)
    monkeypatch.delenv("SUBSYSTEM_NEWS_REASONER_MODEL", raising=False)
    monkeypatch.delenv("SUBSYSTEM_NEWS_REASONER_FALLBACK_BACKEND", raising=False)

    sdk_client = FakeSdkClient()
    result = run_once(
        PipelineConfig(
            allowlist_path=FIXTURE_ROOT / "approved_sources.json",
            artifact_root=tmp_path / "artifacts",
            dedupe_root=tmp_path / "dedupe",
            trace_root=tmp_path / "trace",
            dry_run=False,
        ),
        configs=load_allowlist(FIXTURE_ROOT / "approved_sources.json"),
        entity_client=_RuntimeEntityRegistryClient(),
        sdk_client=sdk_client,
        reasoner_factories=factories,
        transport=StaticTransport(
            {
                "https://runtime.example.com/api/primary": (
                    FIXTURE_ROOT / "primary_api_response.json"
                ).read_text(encoding="utf-8"),
                "https://runtime.example.com/api/secondary": (
                    FIXTURE_ROOT / "secondary_api_response.json"
                ).read_text(encoding="utf-8"),
            }
        ),
    )
    assert sdk_client.calls
    return result


class _RuntimeEntityRegistryClient:
    def __init__(self) -> None:
        aliases = {
            name: RegistryLookup(
                canonical_id=f"entity:{name.lower().replace(' ', '-')}",
                canonical_name=name,
                entity_type="company",
                confidence=0.99,
            )
            for name in (
                "Acme Corp",
                "Globex Inc",
                "North River Metals",
                "East Power Ltd",
                "West Retail PLC",
            )
        }
        self._delegate = StubEntityRegistryClient(alias_results=aliases)

    def lookup_alias(
        self,
        name: str,
        *,
        type_hint: str | None = None,
    ) -> RegistryLookup | None:
        return self._delegate.lookup_alias(name, type_hint=type_hint)

    def resolve_mentions(
        self,
        mentions: Sequence[RegistryMention],
    ) -> list[RegistryResolution]:
        return self._delegate.resolve_mentions(mentions)

    def record_resolution_case(self, case: ResolutionCase) -> None:
        self._delegate.record_resolution_case(case)


def _freeze_api_fetch_time(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr("subsystem_news.sources.api.datetime", _FixedDatetime)


def _ex2_payloads(result: PipelineRunResult) -> list[dict[str, object]]:
    payloads = [
        signal.model_dump(mode="json")
        for article in result.article_results
        if article.context is not None
        for signal in article.context.signals
    ]
    return sorted(payloads, key=lambda payload: str(payload["candidate_id"]))


def _runtime_contract_snapshot(result: PipelineRunResult) -> list[dict[str, object]]:
    snapshots: list[dict[str, object]] = []
    for article in result.article_results:
        if article.context is None:
            continue
        candidates = [
            *article.context.facts,
            *article.context.signals,
            *article.context.graph_deltas,
        ]
        snapshots.append(
            {
                "article_id": article.context.article_id,
                "source_reference": article.context.source_reference.model_dump(
                    mode="json"
                ),
                "schema_pins": {
                    key: value.model_dump(mode="json")
                    for key, value in sorted(article.context.schema_pins.items())
                },
                "candidate_payloads": [
                    candidate.model_dump(mode="json") for candidate in candidates
                ],
                "evidence_spans": [
                    [
                        span.model_dump(mode="json")
                        for span in candidate.evidence_spans
                    ]
                    for candidate in candidates
                ],
            }
        )
    return sorted(snapshots, key=lambda snapshot: str(snapshot["article_id"]))


def _request_contract_surface(
    request: StructuredGenerationRequest,
) -> dict[str, object]:
    return {
        "schema_name": request.schema_name,
        "schema_version": request.schema_version,
        "contract": request.contract,
        "model_output_version": request.model_output_version,
        "input_payload": request.input_payload,
    }


def _load_fact(name: str) -> NewsFactCandidate:
    payload = json.loads(
        (Path("src/subsystem_news/fixtures/signals") / name).read_text(
            encoding="utf-8"
        )
    )
    return NewsFactCandidate.model_validate(payload["fact"])
