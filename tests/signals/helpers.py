from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from subsystem_news.contracts.candidates import NewsFactCandidate
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.signals.direction_judge import SignalJudgement


FIXTURE_ROOT = Path("src/subsystem_news/fixtures/signals")


class FakeReasonerRuntimeClient:
    def __init__(
        self,
        responses: Mapping[str, Mapping[str, object]] | Mapping[str, object],
    ) -> None:
        self.responses = responses
        self.requests: list[StructuredGenerationRequest] = []

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        self.requests.append(request)
        fact = request.input_payload["fact"]
        if not isinstance(fact, Mapping):
            raise AssertionError("request fact payload must be a mapping")
        candidate_id = fact["candidate_id"]
        if candidate_id in self.responses:
            response = self.responses[candidate_id]  # type: ignore[index]
            if not isinstance(response, Mapping):
                raise AssertionError("fake response must be a mapping")
            return response
        return self.responses


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def load_fact(name: str) -> NewsFactCandidate:
    return NewsFactCandidate.model_validate(load_fixture(name)["fact"])


def load_facts(name: str) -> list[NewsFactCandidate]:
    return [
        NewsFactCandidate.model_validate(payload)
        for payload in load_fixture(name)["facts"]
    ]


def load_judgement(name: str) -> SignalJudgement:
    return SignalJudgement.model_validate(load_fixture(name)["judgement"])


def clone_fact(fact: NewsFactCandidate, **updates: object) -> NewsFactCandidate:
    payload = fact.model_dump(mode="json")
    payload.update(updates)
    return NewsFactCandidate.model_validate(payload)
