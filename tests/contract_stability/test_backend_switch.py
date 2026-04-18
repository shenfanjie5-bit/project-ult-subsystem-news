from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from subsystem_news.contracts.candidates import NewsFactCandidate, NewsSignalCandidate
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.runtime.backend_config import RuntimeBackendConfig, resolve_reasoner_client
from subsystem_news.signals.aggregator import build_signal_candidate
from subsystem_news.signals.direction_judge import judge_direction
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN


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
