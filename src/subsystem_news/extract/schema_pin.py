"""Schema/version pinning for structured extraction requests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SchemaPin(BaseModel):
    """Version metadata sent with every structured generation request."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    schema_name: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    contract: Literal["Ex-1", "Ex-2"]
    model_output_version: str = Field(min_length=1)


FACT_SCHEMA_PIN = SchemaPin(
    schema_name="news_fact_candidate",
    schema_version="news_fact_candidate.v1",
    contract="Ex-1",
    model_output_version="news_fact_candidate.output.v1",
)
