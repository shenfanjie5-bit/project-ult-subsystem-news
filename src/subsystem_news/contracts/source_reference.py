"""Traceable source reference contract models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class SourceReferenceLocator(BaseModel):
    """Original provider locator metadata for a fetched article."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    locator_type: str = Field(min_length=1)
    locator_value: str = Field(min_length=1)


class SourceReference(BaseModel):
    """Frozen reference that keeps artifacts traceable to their source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    url: HttpUrl | None = None
    provider_key: str | None = Field(default=None, min_length=1)
    original_locator: SourceReferenceLocator

    @model_validator(mode="after")
    def validate_external_locator(self) -> "SourceReference":
        if self.url is None and self.provider_key is None:
            raise ValueError("source_reference requires url or provider_key")
        return self
