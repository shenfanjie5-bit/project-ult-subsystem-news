from __future__ import annotations

import json
from pathlib import Path

import pytest

from subsystem_news.contracts.article import NewsArticleArtifact
from subsystem_news.entities import (
    RegistryCandidate,
    RegistryResolution,
    StubEntityRegistryClient,
    detect_mentions,
    resolve_article_entities,
    resolve_detected_mentions,
    unresolved_entity,
)
from subsystem_news.entities.resolver_client import RegistryMention
from subsystem_news.errors import EntityResolutionError


FIXTURE_ROOT = Path("src/subsystem_news/fixtures/entities")


def load_article(name: str) -> NewsArticleArtifact:
    return NewsArticleArtifact.model_validate(json.loads((FIXTURE_ROOT / name).read_text()))


def test_quick_path_lookup_alias_hits_before_batch_and_outputs_resolved_entities() -> None:
    article = load_article("single_source_standard.json")
    client = StubEntityRegistryClient(
        alias_results={
            ("Acme Corp", "company"): {"canonical_id": "entity:acme", "entity_type": "company"},
            ("Globex Inc", "company"): {
                "canonical_id": "entity:globex",
                "entity_type": "company",
            },
            ("NASDAQ:ACME", "stock_code"): {
                "canonical_id": "entity:acme",
                "entity_type": "company",
            },
            ("CATL", "standard_abbreviation"): {
                "canonical_id": "entity:catl",
                "entity_type": "company",
            },
        }
    )

    result = resolve_detected_mentions(detect_mentions(article), client)

    assert ("Acme Corp", "company") in client.lookup_calls
    assert ("NASDAQ:ACME", "stock_code") in client.lookup_calls
    assert all(call[0] != "battery modules" for call in client.lookup_calls)
    assert client.resolve_calls
    assert {mention.text for mention in client.resolve_calls[0]} == {
        "battery module",
        "supply contract",
        "battery modules",
    }
    assert {
        (entity.mention_text, entity.canonical_id, entity.resolution_status, entity.type_hint)
        for entity in result.entities
    } >= {
        ("Acme Corp", "entity:acme", "resolved", "company"),
        ("Globex Inc", "entity:globex", "resolved", "company"),
        ("CATL", "entity:catl", "resolved", "standard_abbreviation"),
    }


def test_quick_path_misses_enter_batch_resolution_for_cross_language_alias() -> None:
    article = load_article("cross_language_alias.json")
    client = StubEntityRegistryClient(
        resolutions={
            "宁德时代": RegistryResolution(
                mention_id="placeholder",
                status="resolved",
                canonical_id="entity:catl",
                canonical_name="CATL",
                entity_type="company",
            )
        }
    )

    result = resolve_detected_mentions(detect_mentions(article), client)

    assert ("宁德时代", "company") in client.lookup_calls
    assert client.resolve_calls
    assert "宁德时代" in {mention.text for mention in client.resolve_calls[0]}
    assert any(
        entity.canonical_id == "entity:catl" and entity.resolution_status == "resolved"
        for entity in result.entities
    )


def test_ambiguous_result_records_case_and_never_sets_canonical_id() -> None:
    article = load_article("ambiguous_alias.json")
    candidates = [
        RegistryCandidate(
            canonical_id="entity:mercury-energy-us",
            canonical_name="Mercury Energy LLC",
            entity_type="company",
            confidence=0.51,
        ),
        RegistryCandidate(
            canonical_id="entity:mercury-energy-eu",
            canonical_name="Mercury Energy PLC",
            entity_type="company",
            confidence=0.49,
        ),
    ]
    client = StubEntityRegistryClient(
        resolutions={
            "Mercury Energy": RegistryResolution(
                mention_id="placeholder",
                status="ambiguous",
                candidates=candidates,
                reason="multiple registry candidates",
            )
        }
    )

    result = resolve_detected_mentions(detect_mentions(article), client)

    mercury = next(entity for entity in result.entities if entity.mention_text == "Mercury Energy")
    assert mercury.resolution_status == "ambiguous"
    assert mercury.canonical_id is None
    ambiguous_cases = [
        case for case in client.recorded_cases if case.mention_text == "Mercury Energy"
    ]
    assert ambiguous_cases
    assert ambiguous_cases[0].candidates == candidates


def test_unresolved_result_records_case_without_fabricating_canonical_id() -> None:
    article = load_article("topic_only.json")
    client = StubEntityRegistryClient()

    result = resolve_detected_mentions(detect_mentions(article), client)

    assert {entity.resolution_status for entity in result.entities} == {"unresolved"}
    assert all(entity.canonical_id is None for entity in result.entities)
    assert {entity.mention_text for entity in result.entities} == {"AI chips", "battery modules"}
    assert client.recorded_cases
    assert all(case.resolution_status == "unresolved" for case in client.recorded_cases)


def test_unresolved_fallback_survives_resolution_case_record_failure() -> None:
    article = load_article("topic_only.json")
    client = StubEntityRegistryClient(record_exception=EntityResolutionError("trace down"))

    result = resolve_detected_mentions(detect_mentions(article), client)

    assert result.entities
    assert {entity.resolution_status for entity in result.entities} == {"unresolved"}
    assert all(entity.canonical_id is None for entity in result.entities)
    assert result.resolved_mentions
    assert all(resolved.trace_error is not None for resolved in result.resolved_mentions)
    assert client.recorded_cases == []


def test_resolve_article_entities_returns_stable_deduped_entities() -> None:
    article = load_article("single_source_standard.json")
    client = StubEntityRegistryClient(
        alias_results={
            ("Acme Corp", "company"): {"canonical_id": "entity:acme"},
            ("Globex Inc", "company"): {"canonical_id": "entity:globex"},
            ("NASDAQ:ACME", "stock_code"): {"canonical_id": "entity:acme"},
            ("CATL", "standard_abbreviation"): {"canonical_id": "entity:catl"},
        }
    )

    entities = resolve_article_entities(article, client)

    assert [entity.canonical_id for entity in entities if entity.resolution_status == "resolved"] == [
        "entity:acme",
        "entity:globex",
        "entity:catl",
    ]
    assert entities[0].mention_text == "Acme Corp"
    assert entities[0].type_hint == "company"


def test_registry_systemic_failure_raises_without_case_recording() -> None:
    article = load_article("registry_error.json")
    client = StubEntityRegistryClient(resolve_exception=TimeoutError("registry timed out"))

    with pytest.raises(EntityResolutionError, match="resolve_mentions failed"):
        resolve_detected_mentions(detect_mentions(article), client)

    assert client.recorded_cases == []


def test_single_missing_resolution_falls_back_to_unresolved() -> None:
    article = load_article("registry_error.json")
    mentions = detect_mentions(article)

    class MissingFirstResolutionClient(StubEntityRegistryClient):
        def resolve_mentions(self, mentions: list[RegistryMention]):  # type: ignore[override]
            self.resolve_calls.append(list(mentions))
            return []

    client = MissingFirstResolutionClient()

    result = resolve_detected_mentions(mentions, client)

    assert result.entities
    assert all(entity.resolution_status == "unresolved" for entity in result.entities)
    assert all(entity.canonical_id is None for entity in result.entities)
    assert client.recorded_cases


def test_fallback_helpers_satisfy_involved_entity_contract() -> None:
    mention = detect_mentions(load_article("registry_error.json"))[0]

    entity = unresolved_entity(mention)

    assert entity.resolution_status == "unresolved"
    assert entity.canonical_id is None
