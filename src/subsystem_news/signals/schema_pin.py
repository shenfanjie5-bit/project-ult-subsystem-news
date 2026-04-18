"""Schema/version pinning for Ex-2 signal judgement."""

from __future__ import annotations

from subsystem_news.extract.schema_pin import SchemaPin


SIGNAL_SCHEMA_PIN = SchemaPin(
    schema_name="news_signal_candidate",
    schema_version="news_signal_candidate.v1",
    contract="Ex-2",
    model_output_version="news_signal_candidate.output.v1",
)

__all__ = ["SIGNAL_SCHEMA_PIN"]
