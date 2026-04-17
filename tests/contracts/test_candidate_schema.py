from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
    NewsSignalCandidate,
)
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference
from subsystem_news.errors import EvidenceMissingError


PUBLISHED_AT = datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)
FETCHED_AT = datetime(2026, 1, 15, 10, 35, tzinfo=timezone.utc)
SOURCE_REFERENCE = {
    "source_id": "global-wire-rss",
    "url": "https://news.example.com/articles/1",
    "provider_key": "wire-article-1",
    "original_locator": {
        "locator_type": "rss_guid",
        "locator_value": "wire-article-1",
    },
}


def entity_payload(name: str = "Acme Corp") -> dict[str, str | None]:
    return {
        "mention_text": name,
        "canonical_id": f"entity:{name.lower().replace(' ', '-')}",
        "resolution_status": "resolved",
        "type_hint": "company",
    }


def evidence_payload() -> dict[str, int | str]:
    return {
        "article_id": "article-1",
        "start_char": 10,
        "end_char": 42,
        "quote": "Acme Corp announced a new supply contract.",
        "locator": "body",
    }


def fact_payload() -> dict[str, Any]:
    return {
        "candidate_id": "fact-1",
        "article_id": "article-1",
        "cluster_id": "cluster-1",
        "source_reference": SOURCE_REFERENCE,
        "fact_type": "contract",
        "summary": "Acme announced a new supply contract.",
        "involved_entities": [entity_payload()],
        "event_time": PUBLISHED_AT,
        "evidence_spans": [evidence_payload()],
        "confidence": 0.91,
        "source_reliability_tier": "A",
        "export_contract": "Ex-1",
    }


def signal_payload() -> dict[str, Any]:
    return {
        "candidate_id": "signal-1",
        "article_id": "article-1",
        "cluster_id": "cluster-1",
        "source_reference": SOURCE_REFERENCE,
        "signal_type": "event_impact",
        "direction": "positive",
        "magnitude": 0.7,
        "affected_entities": [entity_payload()],
        "impact_scope": "company",
        "time_horizon": "short",
        "rationale": "The article states a signed supply contract.",
        "evidence_spans": [evidence_payload()],
        "confidence": 0.88,
        "export_contract": "Ex-2",
    }


def graph_payload() -> dict[str, Any]:
    return {
        "candidate_id": "graph-1",
        "article_id": "article-1",
        "source_reference": SOURCE_REFERENCE,
        "subject_entity": entity_payload("Acme Corp"),
        "relation_type": "supplier_of",
        "object_entity": entity_payload("Globex Inc"),
        "delta_action": "add",
        "valid_from": PUBLISHED_AT,
        "evidence_spans": [evidence_payload()],
        "confidence": 0.93,
        "requires_manual_review": True,
        "export_contract": "Ex-3",
    }


def article_payload() -> dict[str, Any]:
    return {
        "article_id": "article-1",
        "source_id": "global-wire-rss",
        "source_reference": SOURCE_REFERENCE,
        "title": "Acme signs a new supply contract",
        "body_text": "Acme Corp announced a new supply contract with Globex Inc.",
        "published_at": PUBLISHED_AT,
        "fetched_at": FETCHED_AT,
        "language": "en",
        "author_or_channel": "Markets Desk",
        "content_hash": "sha256:raw",
        "article_fingerprint": "fingerprint-1",
        "license_tag": "licensed-wire",
        "reliability_tier": "A",
        "cluster_id": "cluster-1",
    }


def cluster_payload() -> dict[str, Any]:
    return {
        "cluster_id": "cluster-1",
        "representative_article_id": "article-1",
        "member_article_ids": ["article-1", "article-2"],
        "canonical_headline": "Acme signs supply contract",
        "first_published_at": PUBLISHED_AT,
        "source_count": 2,
        "fingerprint_family": "supply-contract",
        "cluster_confidence": 0.95,
    }


def assert_round_trip(model: object) -> None:
    json_payload = model.model_dump_json()  # type: ignore[attr-defined]
    restored = type(model).model_validate_json(json_payload)

    assert restored == model


def malformed_source_reference_payload() -> dict[str, Any]:
    return {
        "source_id": "global-wire-rss",
        "url": "not a url",
        "provider_key": "wire-article-1",
        "original_locator": {
            "locator_type": "rss_guid",
            "locator_value": "wire-article-1",
        },
    }


def test_source_reference_valid_sample_passes() -> None:
    source_reference = SourceReference.model_validate(SOURCE_REFERENCE)

    assert source_reference.source_id == "global-wire-rss"
    assert source_reference.provider_key == "wire-article-1"
    assert source_reference.original_locator.locator_value == "wire-article-1"


def test_source_reference_valid_provider_key_only_sample_passes() -> None:
    payload = dict(SOURCE_REFERENCE)
    del payload["url"]

    source_reference = SourceReference.model_validate(payload)

    assert source_reference.url is None
    assert source_reference.provider_key == "wire-article-1"


@pytest.mark.parametrize(
    "source_reference",
    [
        {},
        {
            "source_id": "global-wire-rss",
            "original_locator": {
                "locator_type": "rss_guid",
                "locator_value": "wire-article-1",
            },
        },
        {
            "source_id": "global-wire-rss",
            "url": "not a url",
            "original_locator": {
                "locator_type": "rss_guid",
                "locator_value": "wire-article-1",
            },
        },
        {
            "source_id": "global-wire-rss",
            "url": "https://news.example.com/articles/1",
            "original_locator": {},
        },
    ],
)
def test_source_reference_empty_or_malformed_payloads_are_rejected(
    source_reference: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        SourceReference.model_validate(source_reference)


def test_article_artifact_valid_sample_passes() -> None:
    article = NewsArticleArtifact.model_validate(article_payload())

    assert article.article_id == "article-1"
    assert article.cluster_id == "cluster-1"
    assert isinstance(article.source_reference, SourceReference)


def test_article_artifact_missing_required_field_rejected() -> None:
    payload = article_payload()
    del payload["source_reference"]

    with pytest.raises(ValidationError) as exc_info:
        NewsArticleArtifact.model_validate(payload)

    assert "source_reference" in str(exc_info.value)


def test_article_artifact_source_reference_must_match_source_id() -> None:
    payload = article_payload()
    payload["source_reference"] = {
        **SOURCE_REFERENCE,
        "source_id": "other-source",
    }

    with pytest.raises(ValidationError) as exc_info:
        NewsArticleArtifact.model_validate(payload)

    assert "source_reference.source_id must match source_id" in str(exc_info.value)


@pytest.mark.parametrize(
    "model_type,payload_factory",
    [
        (NewsArticleArtifact, article_payload),
        (NewsFactCandidate, fact_payload),
        (NewsSignalCandidate, signal_payload),
        (NewsGraphDeltaCandidate, graph_payload),
    ],
)
@pytest.mark.parametrize("source_reference", [{}, malformed_source_reference_payload()])
def test_contract_models_reject_empty_or_malformed_source_reference(
    model_type: type[
        NewsArticleArtifact | NewsFactCandidate | NewsSignalCandidate | NewsGraphDeltaCandidate
    ],
    payload_factory: Callable[[], dict[str, Any]],
    source_reference: dict[str, Any],
) -> None:
    payload = payload_factory()
    payload["source_reference"] = source_reference

    with pytest.raises(ValidationError) as exc_info:
        model_type.model_validate(payload)

    assert "source_reference" in str(exc_info.value)


def test_article_artifact_invalid_enum_rejected_with_allowed_values() -> None:
    payload = article_payload()
    payload["reliability_tier"] = "D"

    with pytest.raises(ValidationError) as exc_info:
        NewsArticleArtifact.model_validate(payload)

    message = str(exc_info.value)
    assert "A" in message
    assert "B" in message
    assert "C" in message


def test_dedupe_cluster_valid_sample_passes() -> None:
    cluster = NewsDedupeCluster.model_validate(cluster_payload())

    assert cluster.cluster_id == "cluster-1"
    assert cluster.source_count == 2


def test_dedupe_cluster_missing_required_field_rejected() -> None:
    payload = cluster_payload()
    del payload["representative_article_id"]

    with pytest.raises(ValidationError) as exc_info:
        NewsDedupeCluster.model_validate(payload)

    assert "representative_article_id" in str(exc_info.value)


def test_dedupe_cluster_invalid_confidence_rejected() -> None:
    payload = cluster_payload()
    payload["cluster_confidence"] = 1.5

    with pytest.raises(ValidationError) as exc_info:
        NewsDedupeCluster.model_validate(payload)

    assert "cluster_confidence" in str(exc_info.value)


def test_evidence_span_valid_sample_passes() -> None:
    span = EvidenceSpan.model_validate(evidence_payload())

    assert span.locator == "body"
    assert span.end_char > span.start_char


def test_evidence_span_missing_required_field_rejected() -> None:
    payload = evidence_payload()
    del payload["quote"]

    with pytest.raises(ValidationError) as exc_info:
        EvidenceSpan.model_validate(payload)

    assert "quote" in str(exc_info.value)


def test_evidence_span_invalid_enum_rejected_with_allowed_values() -> None:
    payload = evidence_payload()
    payload["locator"] = "summary"

    with pytest.raises(ValidationError) as exc_info:
        EvidenceSpan.model_validate(payload)

    message = str(exc_info.value)
    assert "title" in message
    assert "body" in message


def test_evidence_span_rejects_non_positive_width() -> None:
    payload = evidence_payload()
    payload["end_char"] = payload["start_char"]

    with pytest.raises(ValidationError) as exc_info:
        EvidenceSpan.model_validate(payload)

    assert "end_char must be greater than start_char" in str(exc_info.value)


def test_involved_entity_valid_sample_passes() -> None:
    entity = InvolvedEntity.model_validate(entity_payload())

    assert entity.resolution_status == "resolved"
    assert entity.canonical_id == "entity:acme-corp"


def test_involved_entity_missing_required_field_rejected() -> None:
    payload = entity_payload()
    del payload["mention_text"]

    with pytest.raises(ValidationError) as exc_info:
        InvolvedEntity.model_validate(payload)

    assert "mention_text" in str(exc_info.value)


def test_involved_entity_invalid_enum_rejected_with_allowed_values() -> None:
    payload = entity_payload()
    payload["resolution_status"] = "guessed"

    with pytest.raises(ValidationError) as exc_info:
        InvolvedEntity.model_validate(payload)

    message = str(exc_info.value)
    assert "resolved" in message
    assert "unresolved" in message
    assert "ambiguous" in message


def test_fact_candidate_valid_sample_passes() -> None:
    candidate = NewsFactCandidate.model_validate(fact_payload())

    assert candidate.export_contract == "Ex-1"
    assert candidate.evidence_spans


def test_fact_candidate_missing_evidence_field_rejected() -> None:
    payload = fact_payload()
    del payload["evidence_spans"]

    with pytest.raises(ValidationError) as exc_info:
        NewsFactCandidate.model_validate(payload)

    assert "evidence_spans" in str(exc_info.value)


def test_fact_candidate_empty_evidence_rejected_with_domain_error() -> None:
    payload = fact_payload()
    payload["evidence_spans"] = []

    with pytest.raises(EvidenceMissingError):
        NewsFactCandidate.model_validate(payload)


def test_fact_candidate_invalid_enum_rejected_with_allowed_values() -> None:
    payload = fact_payload()
    payload["fact_type"] = "rumor"

    with pytest.raises(ValidationError) as exc_info:
        NewsFactCandidate.model_validate(payload)

    message = str(exc_info.value)
    assert "accident" in message
    assert "contract" in message
    assert "litigation" in message


@pytest.mark.parametrize("missing_field", ["direction", "magnitude", "affected_entities"])
def test_signal_candidate_missing_required_signal_fields_rejected(missing_field: str) -> None:
    payload = signal_payload()
    del payload[missing_field]

    with pytest.raises(ValidationError) as exc_info:
        NewsSignalCandidate.model_validate(payload)

    assert missing_field in str(exc_info.value)


def test_signal_candidate_valid_sample_passes() -> None:
    candidate = NewsSignalCandidate.model_validate(signal_payload())

    assert candidate.export_contract == "Ex-2"
    assert candidate.direction == "positive"


def test_signal_candidate_invalid_enum_rejected_with_allowed_values() -> None:
    payload = signal_payload()
    payload["impact_scope"] = "macro"

    with pytest.raises(ValidationError) as exc_info:
        NewsSignalCandidate.model_validate(payload)

    message = str(exc_info.value)
    assert "company" in message
    assert "sector" in message
    assert "market_theme" in message


@pytest.mark.parametrize("missing_field", ["subject_entity", "object_entity"])
def test_graph_delta_candidate_missing_required_entities_rejected(missing_field: str) -> None:
    payload = graph_payload()
    del payload[missing_field]

    with pytest.raises(ValidationError) as exc_info:
        NewsGraphDeltaCandidate.model_validate(payload)

    assert missing_field in str(exc_info.value)


def test_graph_delta_candidate_valid_sample_passes() -> None:
    candidate = NewsGraphDeltaCandidate.model_validate(graph_payload())

    assert candidate.export_contract == "Ex-3"
    assert candidate.requires_manual_review is True


def test_graph_delta_candidate_invalid_enum_rejected_with_allowed_values() -> None:
    payload = graph_payload()
    payload["relation_type"] = "co_mentioned"

    with pytest.raises(ValidationError) as exc_info:
        NewsGraphDeltaCandidate.model_validate(payload)

    message = str(exc_info.value)
    assert "supplier_of" in message
    assert "sanctioned_by" in message
    assert "divested" in message


@pytest.mark.parametrize(
    "model_type,payload",
    [
        (NewsFactCandidate, fact_payload()),
        (NewsSignalCandidate, signal_payload()),
        (NewsGraphDeltaCandidate, graph_payload()),
    ],
)
def test_candidate_json_round_trip_preserves_fields(
    model_type: type[NewsFactCandidate | NewsSignalCandidate | NewsGraphDeltaCandidate],
    payload: dict[str, Any],
) -> None:
    candidate = model_type.model_validate(payload)

    assert_round_trip(candidate)
