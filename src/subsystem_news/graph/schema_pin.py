"""Schema/version pinning for high-threshold Ex-3 graph extraction."""

from __future__ import annotations

from subsystem_news.extract.schema_pin import SchemaPin


GRAPH_SCHEMA_PIN = SchemaPin(
    schema_name="news_graph_delta_candidate",
    schema_version="news_graph_delta_candidate.v1",
    contract="Ex-3",
    model_output_version="news_graph_delta_candidate.output.v1",
)

__all__ = ["GRAPH_SCHEMA_PIN"]
