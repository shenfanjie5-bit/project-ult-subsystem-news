from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

import pytest

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.contracts.candidates import (
    InvolvedEntity,
    NewsFactCandidate,
    NewsGraphDeltaCandidate,
)
from subsystem_news.contracts.cluster import NewsDedupeCluster
from subsystem_news.contracts.evidence import EvidenceSpan
from subsystem_news.contracts.source_reference import SourceReference, SourceReferenceLocator
from subsystem_news.entities.mention import Mention
from subsystem_news.entities.resolution import EntityResolutionResult, ResolvedMention
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.schema_pin import SchemaPin
from subsystem_news.graph import (
    GRAPH_SCHEMA_PIN,
    RelationExtractionInput,
    build_graph_delta_candidate,
    extract_graph_deltas,
    validate_graph_evidence,
)
from subsystem_news.graph.prompt import build_relation_extraction_request


class FakeReasonerRuntimeClient:
    def __init__(self, response: Mapping[str, object]):
        self.response = response
        self.requests = []

    def generate_structured(self, request):
        self.requests.append(request)
        return self.response


@pytest.mark.parametrize(
    ("relation_type", "body_text", "subject_text", "object_text", "fact_type"),
    [
        (
            "acquired",
            "Acme Corp acquired Globex Inc in a cash transaction.",
            "Acme Corp",
            "Globex Inc",
            "m_and_a",
        ),
        (
            "partner_of",
            "North River Metals entered a strategic partnership with East Power Ltd.",
            "North River Metals",
            "East Power Ltd",
            "contract",
        ),
        (
            "sanctioned_by",
            "Atlas Shipping was sanctioned by State Treasury over exports.",
            "Atlas Shipping",
            "State Treasury",
            "regulation_impact",
        ),
        (
            "supplier_of",
            "Delta Components will supply battery modules to Zenith Motors.",
            "Delta Components",
            "Zenith Motors",
            "supply_chain",
        ),
        (
            "divested",
            "Harbor Energy divested its pipeline unit to Bay Capital.",
            "Harbor Energy",
            "Bay Capital",
            "m_and_a",
        ),
    ],
)
def test_extract_graph_deltas_generates_positive_relations(
    relation_type: str,
    body_text: str,
    subject_text: str,
    object_text: str,
    fact_type: str,
) -> None:
    article, cluster, entity_resolution, facts = graph_input(
        body_text=body_text,
        subject_text=subject_text,
        object_text=object_text,
        fact_type=fact_type,
    )
    response = {
        "graph_deltas": [
            raw_delta(
                article,
                relation_type=relation_type,
                subject=facts[0].involved_entities[0],
                object_entity=facts[0].involved_entities[1],
            )
        ]
    }
    client = FakeReasonerRuntimeClient(response)

    candidates = extract_graph_deltas(
        article,
        cluster,
        entity_resolution,
        facts,
        client,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.export_contract == "Ex-3"
    assert candidate.relation_type == relation_type
    assert candidate.requires_manual_review is True
    assert candidate.source_reference == article.source_reference
    assert candidate.evidence_spans[0].quote == body_text
    assert client.requests[0].contract == "Ex-3"
    assert client.requests[0].schema_version == GRAPH_SCHEMA_PIN.schema_version
    assert "signals" not in client.requests[0].input_payload


def test_validate_graph_evidence_rejects_weak_or_unresolved_candidates() -> None:
    article, _, entity_resolution, facts = graph_input(
        body_text="Acme Corp and Globex Inc attended the same battery expo.",
        subject_text="Acme Corp",
        object_text="Globex Inc",
    )
    weak_candidate = NewsGraphDeltaCandidate.model_validate(
        raw_delta(
            article,
            relation_type="partner_of",
            subject=facts[0].involved_entities[0],
            object_entity=facts[0].involved_entities[1],
        )
        | {
            "candidate_id": "graph-weak",
            "article_id": article.article_id,
            "source_reference": article.source_reference.model_dump(mode="json"),
            "export_contract": "Ex-3",
        }
    )

    with pytest.raises(ContractViolationError, match="explicit relation trigger"):
        validate_graph_evidence(article, weak_candidate, entity_resolution=entity_resolution)

    unresolved = InvolvedEntity(
        mention_text="Globex Inc",
        canonical_id=None,
        resolution_status="unresolved",
        type_hint="company",
    )
    unresolved_candidate = weak_candidate.model_copy(update={"object_entity": unresolved})
    with pytest.raises(ContractViolationError, match="object entity"):
        validate_graph_evidence(
            article,
            unresolved_candidate,
            entity_resolution=entity_resolution,
        )

    mismatch = weak_candidate.model_copy(
        update={
            "evidence_spans": [
                EvidenceSpan(
                    article_id=article.article_id,
                    start_char=0,
                    end_char=9,
                    quote="Wrong text",
                    locator="body",
                )
            ]
        }
    )
    with pytest.raises(ContractViolationError, match="quote"):
        validate_graph_evidence(article, mismatch, entity_resolution=entity_resolution)


def test_extract_graph_deltas_rejects_malformed_runtime_response() -> None:
    article, cluster, entity_resolution, facts = graph_input()

    with pytest.raises(ContractViolationError, match="missing graph_deltas"):
        extract_graph_deltas(
            article,
            cluster,
            entity_resolution,
            facts,
            FakeReasonerRuntimeClient({"facts": []}),
        )
    with pytest.raises(ContractViolationError, match="graph_deltas must be a list"):
        extract_graph_deltas(
            article,
            cluster,
            entity_resolution,
            facts,
            FakeReasonerRuntimeClient({"graph_deltas": None}),
        )


def test_graph_schema_pin_contract_mismatch_is_rejected() -> None:
    article, cluster, entity_resolution, facts = graph_input()
    wrong_pin = SchemaPin(
        schema_name="news_fact_candidate",
        schema_version="news_fact_candidate.v1",
        contract="Ex-1",
        model_output_version="news_fact_candidate.output.v1",
    )

    with pytest.raises(ContractViolationError, match="Ex-3 schema pin"):
        build_relation_extraction_request(
            RelationExtractionInput(
                article=article,
                cluster=cluster,
                entity_resolution=entity_resolution,
                facts=facts,
            ),
            schema_pin=wrong_pin,
        )


def test_build_graph_delta_candidate_filters_unsupported_relation_type() -> None:
    article, _, entity_resolution, facts = graph_input()

    candidate = build_graph_delta_candidate(
        article,
        raw_delta(
            article,
            relation_type="competitor_of",
            subject=facts[0].involved_entities[0],
            object_entity=facts[0].involved_entities[1],
        ),
        entity_resolution,
        source_reference=article.source_reference,
    )

    assert candidate is None


def graph_input(
    *,
    body_text: str = "Acme Corp acquired Globex Inc in a cash transaction.",
    subject_text: str = "Acme Corp",
    object_text: str = "Globex Inc",
    fact_type: str = "m_and_a",
) -> tuple[
    NewsArticleArtifact,
    NewsDedupeCluster,
    EntityResolutionResult,
    list[NewsFactCandidate],
]:
    source_reference = SourceReference(
        source_id="graph-test",
        url="https://news.example.com/graph-test",
        provider_key="graph-test",
        original_locator=SourceReferenceLocator(
            locator_type="fixture",
            locator_value="graph-test",
        ),
    )
    article = NewsArticleArtifact(
        article_id="article-graph-test",
        source_id="graph-test",
        source_reference=source_reference,
        title="Graph relation fixture",
        body_text=body_text,
        published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 3, 1, 0, 5, tzinfo=timezone.utc),
        language="en",
        author_or_channel="Fixture",
        content_hash="sha256:graph-test",
        article_fingerprint="sha256:graph-test-fp",
        license_tag="fixture",
        reliability_tier="A",
        cluster_id="cluster-graph-test",
    )
    cluster = NewsDedupeCluster(
        cluster_id="cluster-graph-test",
        representative_article_id=article.article_id,
        member_article_ids=[article.article_id],
        canonical_headline=article.title,
        first_published_at=article.published_at,
        source_count=1,
        fingerprint_family="sha256:graph-family",
        cluster_confidence=0.94,
    )
    subject = InvolvedEntity(
        mention_text=subject_text,
        canonical_id=f"entity:{subject_text.casefold().replace(' ', '-')}",
        resolution_status="resolved",
        type_hint="company",
    )
    object_entity = InvolvedEntity(
        mention_text=object_text,
        canonical_id=f"entity:{object_text.casefold().replace(' ', '-')}",
        resolution_status="resolved",
        type_hint="company",
    )
    evidence = EvidenceSpan(
        article_id=article.article_id,
        start_char=0,
        end_char=len(body_text),
        quote=body_text,
        locator="body",
    )
    mentions = [
        mention_for(article, source_reference, subject),
        mention_for(article, source_reference, object_entity),
    ]
    entity_resolution = EntityResolutionResult(
        mentions=mentions,
        resolved_mentions=[
            ResolvedMention(
                mention=mentions[0],
                entity=subject,
                resolution_source="quick_path",
                registry_resolution=None,
            ),
            ResolvedMention(
                mention=mentions[1],
                entity=object_entity,
                resolution_source="quick_path",
                registry_resolution=None,
            ),
        ],
        entities=[subject, object_entity],
    )
    fact = NewsFactCandidate(
        candidate_id="fact-graph-test",
        article_id=article.article_id,
        cluster_id=cluster.cluster_id,
        source_reference=source_reference,
        fact_type=fact_type,
        summary=body_text,
        involved_entities=[subject, object_entity],
        event_time=None,
        evidence_spans=[evidence],
        confidence=0.9,
        source_reliability_tier="A",
    )
    return article, cluster, entity_resolution, [fact]


def mention_for(
    article: NewsArticleArtifact,
    source_reference: SourceReference,
    entity: InvolvedEntity,
) -> Mention:
    start = article.body_text.index(entity.mention_text)
    return Mention(
        article_id=article.article_id,
        text=entity.mention_text,
        start_char=start,
        end_char=start + len(entity.mention_text),
        locator="body",
        type_hint=entity.type_hint,
        context=article.body_text,
        source_reference=source_reference,
    )


def raw_delta(
    article: NewsArticleArtifact,
    *,
    relation_type: str,
    subject: InvolvedEntity,
    object_entity: InvolvedEntity,
) -> dict[str, object]:
    return {
        "subject_entity": subject.model_dump(mode="json"),
        "relation_type": relation_type,
        "object_entity": object_entity.model_dump(mode="json"),
        "delta_action": "add",
        "valid_from": None,
        "confidence": 0.91,
        "requires_manual_review": False,
        "evidence_spans": [
            {
                "article_id": article.article_id,
                "start_char": 0,
                "end_char": len(article.body_text),
                "quote": article.body_text,
                "locator": "body",
            }
        ],
    }
