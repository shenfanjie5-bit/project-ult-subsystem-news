"""Evidence span contract models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceSpan(BaseModel):
    """Character span that supports a candidate object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    quote: str
    locator: Literal["title", "body"]

    @model_validator(mode="after")
    def validate_span_order(self) -> "EvidenceSpan":
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self
