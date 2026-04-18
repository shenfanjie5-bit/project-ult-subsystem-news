from __future__ import annotations

from subsystem_news.contracts.candidates import NewsSignalCandidate
from subsystem_news.signals import (
    aggregate_cluster_signals,
    build_signal_candidate,
    generate_signals,
)
from subsystem_news.signals.magnitude import estimate_magnitude

from .helpers import (
    FakeReasonerRuntimeClient,
    clone_fact,
    load_fact,
    load_facts,
    load_fixture,
    load_judgement,
)


def test_build_signal_candidate_backfills_ex2_contract_fields() -> None:
    fact = load_fact("positive_operating_event.json")
    judgement = load_judgement("positive_operating_event.json")
    magnitude = estimate_magnitude(fact, judgement)

    signal = build_signal_candidate(fact, judgement, magnitude=magnitude)

    assert isinstance(signal, NewsSignalCandidate)
    assert signal.candidate_id == "signal:fact-acme-contract-1:event_impact"
    assert signal.article_id == fact.article_id
    assert signal.cluster_id == fact.cluster_id
    assert signal.source_reference == fact.source_reference
    assert signal.affected_entities == fact.involved_entities
    assert signal.evidence_spans == fact.evidence_spans
    assert signal.export_contract == "Ex-2"
    assert signal.direction == "positive"
    assert signal.magnitude == "high"


def test_aggregate_cluster_signals_keeps_highest_confidence_per_cluster_signal_type() -> None:
    first, second = load_facts("repost_cluster.json")
    judgement = load_judgement("repost_cluster.json")
    low_confidence_judgement = judgement.model_copy(update={"confidence": 0.7})
    high_confidence_judgement = judgement.model_copy(update={"confidence": 0.88})
    signals = [
        build_signal_candidate(
            first,
            low_confidence_judgement,
            magnitude=estimate_magnitude(first, low_confidence_judgement),
        ),
        build_signal_candidate(
            second,
            high_confidence_judgement,
            magnitude=estimate_magnitude(second, high_confidence_judgement),
        ),
    ]

    aggregated = aggregate_cluster_signals(signals)

    assert len(aggregated) == 1
    assert aggregated[0].article_id == "article-acme-repost"
    assert aggregated[0].confidence == 0.88


def test_aggregate_cluster_signals_keeps_clusterless_articles_separate() -> None:
    fact = load_fact("positive_operating_event.json")
    judgement = load_judgement("positive_operating_event.json")
    first = build_signal_candidate(
        clone_fact(
            fact,
            candidate_id="fact-no-cluster-a",
            article_id="article-a",
            cluster_id=None,
        ),
        judgement,
        magnitude="medium",
    )
    second = build_signal_candidate(
        clone_fact(
            fact,
            candidate_id="fact-no-cluster-b",
            article_id="article-b",
            cluster_id=None,
        ),
        judgement,
        magnitude="medium",
    )

    aggregated = aggregate_cluster_signals([first, second])

    assert {signal.article_id for signal in aggregated} == {"article-a", "article-b"}


def test_provider_key_collision_fixture_keeps_distinct_clusters() -> None:
    facts = load_facts("provider_key_collision.json")
    assert facts[0].source_reference.provider_key == facts[1].source_reference.provider_key
    assert facts[0].source_reference.source_id != facts[1].source_reference.source_id
    positive = load_judgement("positive_operating_event.json")
    negative = load_judgement("negative_regulatory_litigation_event.json")
    signals = [
        build_signal_candidate(facts[0], positive, magnitude="medium"),
        build_signal_candidate(facts[1], negative, magnitude="high"),
    ]

    aggregated = aggregate_cluster_signals(signals)

    assert len(aggregated) == 2
    assert {signal.cluster_id for signal in aggregated} == {
        "cluster-east-contract",
        "cluster-west-lawsuit",
    }


def test_generate_signals_promotes_judges_builds_and_deamplifies_reposts() -> None:
    facts = load_facts("repost_cluster.json")
    judgement = load_fixture("repost_cluster.json")["judgement"]
    client = FakeReasonerRuntimeClient(
        {
            "fact-acme-contract-wire": {
                "judgement": {**judgement, "confidence": 0.74}
            },
            "fact-acme-contract-repost": {
                "judgement": {**judgement, "confidence": 0.9}
            },
        }
    )

    signals = generate_signals(facts, client)

    assert len(signals) == 1
    assert signals[0].article_id == "article-acme-repost"
    assert signals[0].direction == "positive"
    assert len(client.requests) == 2


def test_generate_signals_rejects_low_confidence_and_ex1_only_without_runtime_call() -> None:
    low_confidence = clone_fact(load_fact("positive_operating_event.json"), confidence=0.2)
    ex1_only = load_fact("ex1_only_boundary.json")
    client = FakeReasonerRuntimeClient(
        {"judgement": load_fixture("positive_operating_event.json")["judgement"]}
    )

    signals = generate_signals([low_confidence, ex1_only], client)

    assert signals == []
    assert client.requests == []
