from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import NewsFactCandidate
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.entities.resolution import EntityResolutionResult
from subsystem_news.errors import ContractViolationError, EvidenceMissingError
from subsystem_news.extract import (
    FACT_SCHEMA_PIN,
    FactExtractionInput,
    ReasonerRuntimeClient,
    SchemaPin,
    StructuredGenerationRequest,
    coerce_evidence_spans,
    extract_facts,
    validate_evidence_spans,
)
from subsystem_news.extract.prompt import build_fact_extraction_request


FIXTURE_ROOT = Path("src/subsystem_news/fixtures/extract")


class FakeReasonerRuntimeClient:
    def __init__(self, response: Mapping[str, object]):
        self.response = response
        self.requests: list[StructuredGenerationRequest] = []

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        self.requests.append(request)
        return self.response


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def load_fact_input(
    name: str = "standard_operating_event.json",
) -> tuple[NewsArticleArtifact, NewsDedupeCluster, EntityResolutionResult, dict[str, Any]]:
    payload = load_fixture(name)
    return (
        NewsArticleArtifact.model_validate(payload["article"]),
        NewsDedupeCluster.model_validate(payload["cluster"]),
        EntityResolutionResult.model_validate(payload["entity_resolution"]),
        payload["runtime_response"],
    )


def test_import_smoke_exports_stable_api() -> None:
    assert FACT_SCHEMA_PIN.contract == "Ex-1"
    assert ReasonerRuntimeClient is not None
    assert SchemaPin is not None
    assert StructuredGenerationRequest is not None
    assert extract_facts is not None
    assert validate_evidence_spans is not None


def test_build_request_includes_schema_pin_contract_schema_source_and_entity_spans() -> None:
    article, cluster, entity_resolution, _ = load_fact_input()
    request = build_fact_extraction_request(
        FactExtractionInput(
            article=article,
            cluster=cluster,
            entity_resolution=entity_resolution,
        )
    )

    assert request.schema_name == FACT_SCHEMA_PIN.schema_name
    assert request.schema_version == "news_fact_candidate.v1"
    assert request.contract == "Ex-1"
    assert request.response_schema == NewsFactCandidate.model_json_schema()
    assert request.input_payload["source_reference"] == article.source_reference.model_dump(
        mode="json"
    )
    assert (
        request.input_payload["representative_article"]["source_reliability_tier"]
        == article.reliability_tier
    )
    assert request.input_payload["cluster"]["cluster_id"] == cluster.cluster_id

    mentions = request.input_payload["entity_resolution"]["mentions"]
    assert {
        "text": "Acme Corp",
        "start_char": 0,
        "end_char": 9,
        "locator": "body",
    }.items() <= mentions[0].items()
    assert "do not invent canonical entities" in request.prompt


def test_schema_pin_regression_fixture_and_custom_version_are_reflected_in_request() -> None:
    expected = load_fixture("schema_pin_regression.json")["expected_schema_pin"]
    assert FACT_SCHEMA_PIN.model_dump(mode="json") == expected

    article, cluster, entity_resolution, _ = load_fact_input()
    custom_pin = SchemaPin(
        schema_name="news_fact_candidate",
        schema_version="news_fact_candidate.v2",
        contract="Ex-1",
        model_output_version="news_fact_candidate.output.v2",
    )
    request = build_fact_extraction_request(
        FactExtractionInput(
            article=article,
            cluster=cluster,
            entity_resolution=entity_resolution,
        ),
        schema_pin=custom_pin,
    )

    assert request.schema_version == "news_fact_candidate.v2"
    assert request.input_payload["schema_pin"]["model_output_version"].endswith(".v2")


def test_extract_facts_happy_path_backfills_trace_fields_and_validates_contract() -> None:
    article, cluster, entity_resolution, response = load_fact_input()
    client = FakeReasonerRuntimeClient(response)

    candidates = extract_facts(article, cluster, entity_resolution, client)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.article_id == article.article_id
    assert candidate.cluster_id == cluster.cluster_id
    assert candidate.source_reference == article.source_reference
    assert candidate.source_reliability_tier == article.reliability_tier
    assert candidate.export_contract == "Ex-1"
    assert candidate.evidence_spans[0].quote == article.body_text[0:77]
    assert client.requests[0].schema_version == FACT_SCHEMA_PIN.schema_version


def test_runtime_trace_fields_are_overwritten_by_local_article_and_cluster() -> None:
    article, cluster, entity_resolution, response = load_fact_input()
    response = copy.deepcopy(response)
    response["facts"][0].update(  # type: ignore[index, union-attr]
        {
            "article_id": "wrong-article",
            "cluster_id": "wrong-cluster",
            "source_reference": {
                "source_id": "wrong-source",
                "provider_key": "wrong-key",
                "original_locator": {
                    "locator_type": "fixture",
                    "locator_value": "wrong-key",
                },
            },
            "source_reliability_tier": "C",
            "export_contract": "Ex-2",
        }
    )

    candidate = extract_facts(
        article,
        cluster,
        entity_resolution,
        FakeReasonerRuntimeClient(response),
    )[0]

    assert candidate.article_id == article.article_id
    assert candidate.cluster_id == cluster.cluster_id
    assert candidate.source_reference == article.source_reference
    assert candidate.source_reliability_tier == "A"
    assert candidate.export_contract == "Ex-1"


def test_extract_facts_rejects_missing_evidence() -> None:
    article, cluster, entity_resolution, response = load_fact_input()
    response = copy.deepcopy(response)
    response["facts"][0]["evidence_spans"] = []  # type: ignore[index]

    with pytest.raises(EvidenceMissingError):
        extract_facts(
            article,
            cluster,
            entity_resolution,
            FakeReasonerRuntimeClient(response),
        )


def test_extract_facts_rejects_quote_mismatch_and_out_of_bounds_evidence() -> None:
    article, cluster, entity_resolution, response = load_fact_input()
    mismatched = copy.deepcopy(response)
    mismatched["facts"][0]["evidence_spans"][0]["quote"] = "Acme signed something else."  # type: ignore[index]

    with pytest.raises(ContractViolationError, match="quote"):
        extract_facts(
            article,
            cluster,
            entity_resolution,
            FakeReasonerRuntimeClient(mismatched),
        )

    out_of_bounds = load_fixture("evidence_out_of_bounds_negative.json")["runtime_response"]
    with pytest.raises(ContractViolationError, match="bounds"):
        extract_facts(
            article,
            cluster,
            entity_resolution,
            FakeReasonerRuntimeClient(out_of_bounds),
        )


def test_coerce_evidence_spans_rejects_negative_offsets_before_quote_matching() -> None:
    article, _, _, _ = load_fact_input()

    with pytest.raises(ContractViolationError, match="non-negative"):
        coerce_evidence_spans(
            article,
            [
                {
                    "article_id": article.article_id,
                    "start_char": -1,
                    "end_char": 4,
                    "quote": "Acme",
                    "locator": "title",
                }
            ],
        )


def test_extract_facts_filters_low_confidence_without_constructing_candidate() -> None:
    article, cluster, entity_resolution, response = load_fact_input()
    low_confidence = copy.deepcopy(response)
    low_confidence["facts"][0]["confidence"] = 0.2  # type: ignore[index]

    assert (
        extract_facts(
            article,
            cluster,
            entity_resolution,
            FakeReasonerRuntimeClient(low_confidence),
        )
        == []
    )


def test_extract_facts_returns_empty_without_calling_runtime_when_entities_are_empty() -> None:
    article, cluster, _, response = load_fact_input()
    empty_resolution = EntityResolutionResult(mentions=[], resolved_mentions=[], entities=[])
    client = FakeReasonerRuntimeClient(response)

    assert extract_facts(article, cluster, empty_resolution, client) == []
    assert client.requests == []


def test_extract_facts_rejects_runtime_extra_fields_and_fabricated_entities() -> None:
    article, cluster, entity_resolution, response = load_fact_input()
    extra_field = copy.deepcopy(response)
    extra_field["facts"][0]["unexpected"] = "must not pass through"  # type: ignore[index]

    with pytest.raises(ContractViolationError):
        extract_facts(
            article,
            cluster,
            entity_resolution,
            FakeReasonerRuntimeClient(extra_field),
        )

    fabricated_entity = copy.deepcopy(response)
    fabricated_entity["facts"][0]["involved_entities"][0] = {  # type: ignore[index]
        "mention_text": "Fabricated Corp",
        "canonical_id": "entity:fabricated",
        "resolution_status": "resolved",
        "type_hint": "company",
    }

    with pytest.raises(ContractViolationError, match="entity_resolution"):
        extract_facts(
            article,
            cluster,
            entity_resolution,
            FakeReasonerRuntimeClient(fabricated_entity),
        )


def test_extract_facts_rejects_non_representative_article_cluster_mismatch() -> None:
    article, cluster, entity_resolution, response = load_fact_input()
    cluster_payload = cluster.model_dump(mode="json")
    cluster_payload["representative_article_id"] = "article-other"
    cluster_payload["member_article_ids"] = ["article-other", "article-other-copy"]
    mismatched_cluster = NewsDedupeCluster.model_validate(cluster_payload)

    with pytest.raises(ContractViolationError, match="identity"):
        extract_facts(
            article,
            mismatched_cluster,
            entity_resolution,
            FakeReasonerRuntimeClient(response),
        )


def test_all_unresolved_boundary_does_not_emit_high_confidence_fact() -> None:
    article, cluster, entity_resolution, response = load_fact_input(
        "all_unresolved_boundary.json"
    )
    client = FakeReasonerRuntimeClient(response)

    assert extract_facts(article, cluster, entity_resolution, client) == []
    assert client.requests
