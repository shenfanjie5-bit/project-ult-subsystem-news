"""Fact extraction and event classification toward Ex-1 candidates."""

from subsystem_news.extract.evidence import coerce_evidence_spans, validate_evidence_spans
from subsystem_news.extract.fact_extractor import FactExtractionInput, extract_facts
from subsystem_news.extract.prompt import FactExtractionResponse
from subsystem_news.extract.runtime_client import (
    ReasonerRuntimeClient,
    StructuredGenerationRequest,
)
from subsystem_news.extract.schema_pin import FACT_SCHEMA_PIN, SchemaPin

__all__ = [
    "FACT_SCHEMA_PIN",
    "FactExtractionInput",
    "FactExtractionResponse",
    "ReasonerRuntimeClient",
    "SchemaPin",
    "StructuredGenerationRequest",
    "coerce_evidence_spans",
    "extract_facts",
    "validate_evidence_spans",
]
