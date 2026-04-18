from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from subsystem_news.contracts.candidates import NewsSignalCandidate
from subsystem_news.entities.resolver_client import RegistryLookup, StubEntityRegistryClient
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.fixtures.loader import load_fixture_suite
from subsystem_news.fixtures.runner import replay_fixture_case
from subsystem_news.runtime.replay import ReplayRequest, ReplayRunResult
from subsystem_news.signals.schema_pin import SIGNAL_SCHEMA_PIN


MANIFEST = Path("src/subsystem_news/fixtures/regression/manifest.json")
FROZEN_EX2_FIELDS = frozenset(NewsSignalCandidate.model_fields)


def test_replay_metadata_exposes_replayed_full_mode_ex2_payloads() -> None:
    result = _replay_case("single-source-standard")
    metadata = result.metadata

    assert result.error_count == 0
    assert {"candidate_payloads", "evidence_spans", "entity_resolutions", "schema_pins"} <= set(
        metadata
    )
    assert metadata["candidate_payloads"]
    assert metadata["evidence_spans"]
    assert metadata["entity_resolutions"]
    assert metadata["schema_pins"]["Ex-2"] == SIGNAL_SCHEMA_PIN.model_dump(mode="json")
    assert _candidate_keys(metadata["candidate_payloads"]) == _replayed_candidate_ids(
        result
    )

    ex2_payloads = [
        payload
        for payload in metadata["candidate_payloads"]
        if payload["export_contract"] == "Ex-2"
    ]
    assert ex2_payloads
    for payload in ex2_payloads:
        candidate = NewsSignalCandidate.model_validate(payload)
        assert frozenset(payload) == FROZEN_EX2_FIELDS
        assert candidate.source_reference
        assert candidate.evidence_spans


def test_ex1_only_replay_keeps_unresolved_mentions_without_ex2_promotion() -> None:
    result = _replay_case("ex1-only-unresolved-boundary")
    payloads = result.metadata["candidate_payloads"]
    ex1_payloads = [
        payload for payload in payloads if payload["export_contract"] == "Ex-1"
    ]
    ex2_payloads = [
        payload for payload in payloads if payload["export_contract"] == "Ex-2"
    ]
    unresolved_entities = [
        entity
        for payload in ex1_payloads
        for entity in payload["involved_entities"]
        if entity["resolution_status"] == "unresolved"
    ]

    assert result.error_count == 0
    assert ex1_payloads
    assert ex2_payloads == []
    assert unresolved_entities
    assert all(entity["canonical_id"] is None for entity in unresolved_entities)
    assert {payload["article_id"] for payload in ex1_payloads} == {
        "article-reg-ex1-only"
    }
    assert {payload["candidate_id"] for payload in ex1_payloads} == {
        "fact-reg-ex1-only-unresolved"
    }


def _replay_case(case_id: str) -> ReplayRunResult:
    suite = load_fixture_suite(MANIFEST)
    case = next(case for case in suite.cases if case.case_id == case_id)
    baseline_path = case.resolved_baseline_path(suite.root_path)

    return replay_fixture_case(
        ReplayRequest(
            case_id=case.case_id,
            category=case.category,
            article_ids=case.article_ids,
            input_path=MANIFEST,
            baseline_path=baseline_path,
            metadata={"fixture_case": case.model_dump(mode="json")},
        ),
        entity_client=_entity_client(),
        reasoner_client=_ReplayContractReasoner(),
    )


def _candidate_keys(payloads: list[dict[str, Any]]) -> set[str]:
    return {
        f"{payload['export_contract']}:{payload['candidate_id']}"
        for payload in payloads
    }


def _replayed_candidate_ids(result: ReplayRunResult) -> set[str]:
    return {
        candidate_id
        for article in result.article_results
        if article.replayed is not None
        for candidate_id in article.replayed.candidate_ids
    }


def _entity_client() -> StubEntityRegistryClient:
    return StubEntityRegistryClient(
        alias_results={
            "Acme Corp": RegistryLookup(
                canonical_id="entity:acme-corp",
                canonical_name="Acme Corp",
                entity_type="company",
                confidence=0.99,
            ),
            "Globex Inc": RegistryLookup(
                canonical_id="entity:globex-inc",
                canonical_name="Globex Inc",
                entity_type="company",
                confidence=0.99,
            ),
        }
    )


class _ReplayContractReasoner:
    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        if request.contract == "Ex-1":
            return {"facts": self._facts(request)}
        if request.contract == "Ex-3":
            return {"graph_deltas": []}
        return {"judgement": self._judgement(request)}

    def _facts(self, request: StructuredGenerationRequest) -> list[dict[str, object]]:
        article = request.input_payload["representative_article"]
        if not isinstance(article, Mapping):
            raise AssertionError("representative_article must be a mapping")
        article_id = str(article["article_id"])
        body = str(article["body_text"])
        entities = _entities_from_request(request)

        if article_id == "article-reg-single-source":
            contract_quote = (
                "Acme Corp signed a three-year supply contract with Globex Inc."
            )
            return [
                {
                    "candidate_id": "fact-reg-single-contract",
                    "fact_type": "contract",
                    "summary": "Acme signed a supply contract with Globex.",
                    "involved_entities": [_entity_named(entities, "Acme Corp")],
                    "event_time": None,
                    "evidence_spans": [_span(article_id, body, contract_quote)],
                    "confidence": 0.9,
                },
            ]

        if article_id == "article-reg-ex1-only":
            quote = (
                "Unlisted Battery Venture announced a storage roadmap without naming "
                "any customer or ticker."
            )
            return [
                {
                    "candidate_id": "fact-reg-ex1-only-unresolved",
                    "fact_type": "product",
                    "summary": "Unlisted Battery Venture announced a storage roadmap.",
                    "involved_entities": [
                        entity
                        for entity in entities
                        if entity["resolution_status"] == "unresolved"
                    ],
                    "event_time": None,
                    "evidence_spans": [_span(article_id, body, quote)],
                    "confidence": 0.9,
                }
            ]

        raise AssertionError(f"unexpected replay article_id {article_id}")

    def _judgement(self, request: StructuredGenerationRequest) -> dict[str, object]:
        fact = request.input_payload["fact"]
        if not isinstance(fact, Mapping):
            raise AssertionError("fact must be a mapping")
        direction = "negative" if fact["fact_type"] == "litigation" else "positive"
        return {
            "signal_type": "event_impact",
            "direction": direction,
            "impact_scope": "company",
            "time_horizon": "short",
            "rationale": "Replay contract metadata judgement.",
            "confidence": 0.84,
        }


def _entities_from_request(
    request: StructuredGenerationRequest,
) -> list[dict[str, object]]:
    entity_resolution = request.input_payload["entity_resolution"]
    if not isinstance(entity_resolution, Mapping):
        raise AssertionError("entity_resolution must be a mapping")
    entities = entity_resolution["entities"]
    if not isinstance(entities, list):
        raise AssertionError("entities must be a list")
    return [dict(entity) for entity in entities if isinstance(entity, Mapping)]


def _entity_named(
    entities: list[dict[str, object]],
    mention_text: str,
) -> dict[str, object]:
    for entity in entities:
        if entity["mention_text"] == mention_text:
            return entity
    raise AssertionError(f"missing entity {mention_text}")


def _span(article_id: str, body: str, quote: str) -> dict[str, object]:
    start = body.index(quote)
    return {
        "article_id": article_id,
        "start_char": start,
        "end_char": start + len(quote),
        "quote": quote,
        "locator": "body",
    }
