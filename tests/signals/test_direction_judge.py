from __future__ import annotations

import pytest

from subsystem_news.contracts.candidates import NewsSignalCandidate
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN
from subsystem_news.signals import (
    SIGNAL_SCHEMA_PIN,
    SignalJudgement,
    generate_signals,
    judge_direction,
)

from .helpers import FakeReasonerRuntimeClient, load_fact, load_fixture


def test_judge_direction_builds_pinned_structured_request() -> None:
    fact = load_fact("positive_operating_event.json")
    judgement_payload = load_fixture("positive_operating_event.json")["judgement"]
    client = FakeReasonerRuntimeClient({"judgement": judgement_payload})

    judgement = judge_direction(fact, client)

    assert isinstance(judgement, SignalJudgement)
    assert judgement.direction == "positive"
    assert judgement.impact_scope == "company"
    request = client.requests[0]
    assert request.schema_name == SIGNAL_SCHEMA_PIN.schema_name
    assert request.schema_version == SIGNAL_SCHEMA_PIN.schema_version
    assert request.contract == "Ex-2"
    assert request.response_schema == NewsSignalCandidate.model_json_schema()
    assert request.input_payload["schema_pin"] == SIGNAL_SCHEMA_PIN.model_dump(mode="json")
    assert request.input_payload["fact"]["summary"] == fact.summary
    assert (
        request.input_payload["evidence_quotes"][0]["quote"]
        == fact.evidence_spans[0].quote
    )
    assert (
        request.input_payload["entity_resolution_statuses"][0]["resolution_status"]
        == "resolved"
    )


@pytest.mark.parametrize("field", ["direction", "impact_scope", "time_horizon"])
def test_judge_direction_rejects_missing_required_semantic_fields(field: str) -> None:
    fact = load_fact("positive_operating_event.json")
    judgement_payload = dict(load_fixture("positive_operating_event.json")["judgement"])
    del judgement_payload[field]
    client = FakeReasonerRuntimeClient({"judgement": judgement_payload})

    with pytest.raises(ContractViolationError, match="missing fields"):
        judge_direction(fact, client)


def test_judge_direction_rejects_null_runtime_semantic_fields() -> None:
    fact = load_fact("positive_operating_event.json")
    judgement_payload = dict(load_fixture("positive_operating_event.json")["judgement"])
    judgement_payload["direction"] = None
    client = FakeReasonerRuntimeClient({"judgement": judgement_payload})

    with pytest.raises(ContractViolationError, match="semantic fields"):
        judge_direction(fact, client)


def test_judge_direction_rejects_fact_schema_pin_before_runtime_call() -> None:
    fact = load_fact("positive_operating_event.json")
    client = FakeReasonerRuntimeClient(
        {"judgement": load_fixture("positive_operating_event.json")["judgement"]}
    )

    with pytest.raises(ContractViolationError, match="SIGNAL_SCHEMA_PIN"):
        judge_direction(fact, client, schema_pin=FACT_SCHEMA_PIN)

    assert client.requests == []


def test_generate_signals_rejects_fact_schema_pin_before_runtime_call() -> None:
    fact = load_fact("positive_operating_event.json")
    client = FakeReasonerRuntimeClient(
        {"judgement": load_fixture("positive_operating_event.json")["judgement"]}
    )

    with pytest.raises(ContractViolationError, match="SIGNAL_SCHEMA_PIN"):
        generate_signals([fact], client, schema_pin=FACT_SCHEMA_PIN)

    assert client.requests == []


def test_signals_modules_do_not_import_prohibited_runtime_dependencies() -> None:
    root = "src/subsystem_news/signals"
    prohibited = (
        "openai",
        "anthropic",
        "kafka",
        "flink",
        "temporal",
        "neo4j",
        "stream_layer",
        "stream-layer",
    )
    from pathlib import Path

    for path in Path(root).glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in prohibited:
            assert token not in text
