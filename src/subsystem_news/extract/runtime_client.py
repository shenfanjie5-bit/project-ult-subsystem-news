"""Structured generation boundary for reasoner-runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class StructuredGenerationRequest(BaseModel):
    """Provider-neutral request passed to reasoner-runtime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_name: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    contract: Literal["Ex-1", "Ex-2", "Ex-3"]
    model_output_version: str = Field(min_length=1)
    response_schema: dict[str, Any]
    prompt: str = Field(min_length=1)
    input_payload: dict[str, Any]


class ReasonerRuntimeClient(Protocol):
    """Minimal structured generation protocol consumed by extract."""

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        """Return structured draft facts for the supplied request."""


class DefaultReasonerRuntimeClient:
    """Adapter around reasoner_runtime.generate_structured."""

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Mapping[str, object]:
        from reasoner_runtime import generate_structured

        result = generate_structured(request.model_dump(mode="json"))
        if not isinstance(result, Mapping):
            raise TypeError("reasoner-runtime generate_structured must return a mapping")
        return result
