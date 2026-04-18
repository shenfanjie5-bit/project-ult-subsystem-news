"""Prompt and payload construction for Ex-3 graph relation extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from subsystem_news.contracts.candidates import NewsGraphDeltaCandidate
from subsystem_news.errors import ContractViolationError
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.extract.schema_pin import SchemaPin
from subsystem_news.graph.schema_pin import GRAPH_SCHEMA_PIN

if TYPE_CHECKING:
    from subsystem_news.graph.relation_extract import RelationExtractionInput


_RELATION_EXTRACTION_PROMPT = """\
Extract only Ex-3 graph deltas supported by explicit relation evidence in the
representative article. Do not infer relationships from co-occurrence, title
association, sentiment, or Ex-2 direction. Use only resolved canonical entities
from the supplied entity trace. Return an object with graph_deltas, a list of
draft NewsGraphDeltaCandidate objects. Each draft must include subject_entity,
relation_type, object_entity, delta_action, valid_from, evidence_spans, and
confidence. Evidence quotes must exactly match title/body slices and contain
explicit relationship language."""


def build_relation_extraction_request(
    input: "RelationExtractionInput",
    *,
    schema_pin: SchemaPin = GRAPH_SCHEMA_PIN,
) -> StructuredGenerationRequest:
    """Build a provider-neutral Ex-3 structured extraction request."""

    _require_graph_schema_pin(schema_pin)
    return StructuredGenerationRequest(
        schema_name=schema_pin.schema_name,
        schema_version=schema_pin.schema_version,
        contract=schema_pin.contract,
        model_output_version=schema_pin.model_output_version,
        response_schema=NewsGraphDeltaCandidate.model_json_schema(),
        prompt=_RELATION_EXTRACTION_PROMPT,
        input_payload={
            "schema_pin": schema_pin.model_dump(mode="json"),
            "cluster": input.cluster.model_dump(mode="json"),
            "representative_article": {
                "article_id": input.article.article_id,
                "source_id": input.article.source_id,
                "title": input.article.title,
                "body_text": input.article.body_text,
                "published_at": input.article.published_at.isoformat(),
                "fetched_at": input.article.fetched_at.isoformat(),
                "source_reference": input.article.source_reference.model_dump(mode="json"),
                "source_reliability_tier": input.article.reliability_tier,
            },
            "source_reference": input.article.source_reference.model_dump(mode="json"),
            "entity_resolution": input.entity_resolution.model_dump(mode="json"),
            "facts": [
                {
                    "candidate_id": fact.candidate_id,
                    "fact_type": fact.fact_type,
                    "summary": fact.summary,
                    "event_time": fact.event_time.isoformat()
                    if fact.event_time is not None
                    else None,
                    "confidence": fact.confidence,
                    "involved_entities": [
                        entity.model_dump(mode="json")
                        for entity in fact.involved_entities
                    ],
                    "evidence_spans": [
                        span.model_dump(mode="json") for span in fact.evidence_spans
                    ],
                }
                for fact in input.facts
            ],
            "evidence_quotes": [
                {
                    "fact_candidate_id": fact.candidate_id,
                    "article_id": span.article_id,
                    "locator": span.locator,
                    "start_char": span.start_char,
                    "end_char": span.end_char,
                    "quote": span.quote,
                }
                for fact in input.facts
                for span in fact.evidence_spans
            ],
        },
    )


def _require_graph_schema_pin(schema_pin: SchemaPin) -> None:
    if schema_pin != GRAPH_SCHEMA_PIN:
        raise ContractViolationError(
            "graph extraction requires news_graph_delta_candidate Ex-3 schema pin"
        )


__all__ = ["build_relation_extraction_request"]
