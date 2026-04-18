"""Prompt and payload construction for Ex-1 fact extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from subsystem_news.contracts.candidates import NewsFactCandidate
from subsystem_news.entities.resolution import EntityResolutionResult
from subsystem_news.extract.runtime_client import StructuredGenerationRequest
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN, SchemaPin

if TYPE_CHECKING:
    from subsystem_news.extract.fact_extractor import FactExtractionInput


_FACT_EXTRACTION_PROMPT = """\
Extract only Ex-1 news facts supported by exact spans in the representative article.
Use the provided entity resolution trace; do not invent canonical entities.
Return draft NewsFactCandidate objects under facts. Each draft must include
candidate_id, fact_type, summary, involved_entities, event_time, evidence_spans,
	and confidence. Evidence quotes must exactly match title/body slices."""


class FactExtractionResponse(BaseModel):
    """Structured Ex-1 runtime response wrapper."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: list[NewsFactCandidate]


def build_fact_extraction_request(
    input: "FactExtractionInput",
    *,
    schema_pin: SchemaPin = FACT_SCHEMA_PIN,
) -> StructuredGenerationRequest:
    """Build a provider-neutral structured extraction request."""

    return StructuredGenerationRequest(
        schema_name=schema_pin.schema_name,
        schema_version=schema_pin.schema_version,
        contract=schema_pin.contract,
        model_output_version=schema_pin.model_output_version,
        response_schema=FactExtractionResponse.model_json_schema(),
        prompt=_FACT_EXTRACTION_PROMPT,
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
            "entity_resolution": _entity_resolution_payload(input.entity_resolution),
        },
    )


def _entity_resolution_payload(result: EntityResolutionResult) -> dict[str, Any]:
    return {
        "mentions": [
            {
                "article_id": mention.article_id,
                "text": mention.text,
                "start_char": mention.start_char,
                "end_char": mention.end_char,
                "locator": mention.locator,
                "type_hint": mention.type_hint,
                "context": mention.context,
                "source_reference": mention.source_reference.model_dump(mode="json"),
            }
            for mention in result.mentions
        ],
        "resolved_mentions": [
            {
                "mention": {
                    "article_id": resolved.mention.article_id,
                    "text": resolved.mention.text,
                    "start_char": resolved.mention.start_char,
                    "end_char": resolved.mention.end_char,
                    "locator": resolved.mention.locator,
                    "type_hint": resolved.mention.type_hint,
                    "context": resolved.mention.context,
                    "source_reference": resolved.mention.source_reference.model_dump(
                        mode="json"
                    ),
                },
                "entity": resolved.entity.model_dump(mode="json"),
                "resolution_source": resolved.resolution_source,
                "registry_resolution": (
                    resolved.registry_resolution.model_dump(mode="json")
                    if resolved.registry_resolution is not None
                    else None
                ),
            }
            for resolved in result.resolved_mentions
        ],
        "entities": [entity.model_dump(mode="json") for entity in result.entities],
    }
